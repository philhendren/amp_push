"""Unit tests for AMPClient.

Nothing here touches the network or real AWS: the boto3 Session passed in
and requests.post are both faked out.
"""

from typing import Any

import boto3
import pytest
import requests
from botocore.credentials import ReadOnlyCredentials

from amp_push import AMPClient, Metric

WORKSPACE_ID = "ws-abc123"
REGION = "eu-west-2"

METRIC = Metric("job_duration_seconds", 12.4, labels={"job": "etl-daily"})


class FakeCredentials:
    def get_frozen_credentials(self) -> ReadOnlyCredentials:
        return ReadOnlyCredentials(
            access_key="AKIDEXAMPLE",
            secret_key="secret",
            token=None,
        )


class FakeSession:
    def __init__(
        self,
        credentials: FakeCredentials | None,
        amp_client: "FakeAmpApiClient | None" = None,
    ) -> None:
        self._credentials = credentials
        self._amp_client = amp_client

    def get_credentials(self) -> FakeCredentials | None:
        return self._credentials

    def client(
        self,
        service_name: str,
        region_name: str | None = None,
    ) -> "FakeAmpApiClient":
        assert service_name == "amp"
        assert region_name == REGION
        assert self._amp_client is not None, "test did not set up a FakeAmpApiClient"
        return self._amp_client


class FakeAmpApiClient:
    """Fakes the boto3 `amp` service client's `list_workspaces`.

    `pages` is one dict per call, returned in order - lets a test simulate
    pagination via `nextToken` without a real paginator.
    """

    def __init__(self, pages: list[dict]) -> None:
        self._pages = pages
        self.calls: list[dict] = []

    def list_workspaces(self, **kwargs: object) -> dict:
        self.calls.append(kwargs)
        return self._pages[len(self.calls) - 1]


class FakeResponse:
    def __init__(self, *, status_code: int = 200, text: str = "") -> None:
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= requests.codes.bad_request:
            message = f"{self.status_code}: {self.text}"
            raise requests.HTTPError(message)


_DEFAULT_CREDENTIALS = object()


def make_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    credentials: FakeCredentials | object | None = _DEFAULT_CREDENTIALS,
    response: FakeResponse | None = None,
    post_error: Exception | None = None,
) -> tuple[AMPClient, dict[str, Any]]:
    """Build a client wired to fakes, and a box to inspect the POST call."""
    if credentials is _DEFAULT_CREDENTIALS:
        credentials = FakeCredentials()
    if response is None:
        response = FakeResponse(status_code=200)

    posted: dict[str, Any] = {}

    def fake_post(url: str, data: bytes, headers: dict, timeout: float) -> FakeResponse:
        if post_error is not None:
            raise post_error
        posted.update(url=url, data=data, headers=headers, timeout=timeout)
        return response

    monkeypatch.setattr("amp_push.client.requests.post", fake_post)

    client = AMPClient(
        workspace_id=WORKSPACE_ID,
        region=REGION,
        session=FakeSession(credentials),
    )
    return client, posted


def test_remote_write_url_matches_the_documented_shape() -> None:
    client = AMPClient(
        workspace_id=WORKSPACE_ID,
        region=REGION,
        session=FakeSession(None),
    )

    assert client.remote_write_url == (
        f"https://aps-workspaces.{REGION}.amazonaws.com"
        f"/workspaces/{WORKSPACE_ID}/api/v1/remote_write"
    )


def test_push_posts_to_the_remote_write_url(monkeypatch: pytest.MonkeyPatch) -> None:
    client, posted = make_client(monkeypatch)

    client.push([METRIC])

    assert posted["url"] == client.remote_write_url


def test_push_sends_the_required_remote_write_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, posted = make_client(monkeypatch)

    client.push([METRIC])

    headers = {k.lower(): v for k, v in posted["headers"].items()}
    assert headers["content-encoding"] == "snappy"
    assert headers["content-type"] == "application/x-protobuf"
    assert headers["x-prometheus-remote-write-version"] == "0.1.0"
    assert "authorization" in headers


def test_push_uses_the_configured_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    custom_timeout = 3.5
    client, posted = make_client(monkeypatch)
    client.timeout = custom_timeout

    client.push([METRIC])

    assert posted["timeout"] == custom_timeout


def test_push_is_a_no_op_for_an_empty_metric_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, posted = make_client(monkeypatch)

    client.push([])

    assert posted == {}


def test_push_raises_when_there_are_no_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _posted = make_client(monkeypatch, credentials=None)

    with pytest.raises(RuntimeError, match="No AWS credentials"):
        client.push([METRIC])


def test_push_raises_on_a_non_ok_http_response(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _posted = make_client(
        monkeypatch,
        response=FakeResponse(status_code=403, text="AccessDenied"),
    )

    with pytest.raises(requests.HTTPError, match="403"):
        client.push([METRIC])


def test_push_propagates_a_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _posted = make_client(
        monkeypatch,
        post_error=requests.ConnectionError("boom"),
    )

    with pytest.raises(requests.ConnectionError, match="boom"):
        client.push([METRIC])


def test_default_session_is_a_real_boto3_session() -> None:
    # No AWS calls made here - constructing a boto3.Session does not touch
    # the network or require credentials to exist.
    client = AMPClient(workspace_id=WORKSPACE_ID, region=REGION)

    assert isinstance(client._session, boto3.Session)  # noqa: SLF001


# --- workspace_alias resolution -------------------------------------------

ALIAS = "prod-services"


def test_constructor_rejects_both_workspace_id_and_workspace_alias() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        AMPClient(workspace_id=WORKSPACE_ID, workspace_alias=ALIAS, region=REGION)


def test_constructor_rejects_neither_workspace_id_nor_workspace_alias() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        AMPClient(region=REGION)


def test_workspace_id_resolves_via_alias_lookup() -> None:
    amp = FakeAmpApiClient(
        pages=[{"workspaces": [{"workspaceId": WORKSPACE_ID, "alias": ALIAS}]}],
    )
    client = AMPClient(
        workspace_alias=ALIAS,
        region=REGION,
        session=FakeSession(FakeCredentials(), amp_client=amp),
    )

    assert client.workspace_id == WORKSPACE_ID
    assert amp.calls == [{"alias": ALIAS}]


def test_workspace_id_resolution_is_cached_after_the_first_lookup() -> None:
    amp = FakeAmpApiClient(
        pages=[{"workspaces": [{"workspaceId": WORKSPACE_ID, "alias": ALIAS}]}],
    )
    client = AMPClient(
        workspace_alias=ALIAS,
        region=REGION,
        session=FakeSession(FakeCredentials(), amp_client=amp),
    )

    assert client.workspace_id == WORKSPACE_ID
    assert client.workspace_id == WORKSPACE_ID
    assert len(amp.calls) == 1


def test_workspace_id_resolution_paginates() -> None:
    amp = FakeAmpApiClient(
        pages=[
            {
                "workspaces": [
                    {"workspaceId": "ws-other", "alias": "prod-services-extra"},
                ],
                "nextToken": "page-2",
            },
            {"workspaces": [{"workspaceId": WORKSPACE_ID, "alias": ALIAS}]},
        ],
    )
    client = AMPClient(
        workspace_alias=ALIAS,
        region=REGION,
        session=FakeSession(FakeCredentials(), amp_client=amp),
    )

    assert client.workspace_id == WORKSPACE_ID
    assert amp.calls == [{"alias": ALIAS}, {"alias": ALIAS, "nextToken": "page-2"}]


def test_workspace_id_resolution_ignores_alias_prefix_matches() -> None:
    # AMP's `alias` filter is a startswith match, not exact - a workspace
    # aliased "prod-services-extra" must not be mistaken for "prod-services".
    amp = FakeAmpApiClient(
        pages=[
            {
                "workspaces": [
                    {"workspaceId": "ws-other", "alias": "prod-services-extra"},
                    {"workspaceId": WORKSPACE_ID, "alias": ALIAS},
                ],
            },
        ],
    )
    client = AMPClient(
        workspace_alias=ALIAS,
        region=REGION,
        session=FakeSession(FakeCredentials(), amp_client=amp),
    )

    assert client.workspace_id == WORKSPACE_ID


def test_workspace_id_resolution_raises_when_no_workspace_matches() -> None:
    amp = FakeAmpApiClient(pages=[{"workspaces": []}])
    client = AMPClient(
        workspace_alias=ALIAS,
        region=REGION,
        session=FakeSession(FakeCredentials(), amp_client=amp),
    )

    with pytest.raises(
        ValueError,
        match=f"No AMP workspace found with alias {ALIAS!r}",
    ):
        _ = client.workspace_id


def test_workspace_id_resolution_raises_when_multiple_workspaces_match() -> None:
    amp = FakeAmpApiClient(
        pages=[
            {
                "workspaces": [
                    {"workspaceId": "ws-one", "alias": ALIAS},
                    {"workspaceId": "ws-two", "alias": ALIAS},
                ],
            },
        ],
    )
    client = AMPClient(
        workspace_alias=ALIAS,
        region=REGION,
        session=FakeSession(FakeCredentials(), amp_client=amp),
    )

    with pytest.raises(ValueError, match="Multiple AMP workspaces have alias"):
        _ = client.workspace_id


def test_remote_write_url_resolves_workspace_alias_lazily() -> None:
    amp = FakeAmpApiClient(
        pages=[{"workspaces": [{"workspaceId": WORKSPACE_ID, "alias": ALIAS}]}],
    )
    client = AMPClient(
        workspace_alias=ALIAS,
        region=REGION,
        session=FakeSession(FakeCredentials(), amp_client=amp),
    )

    assert (
        amp.calls == []
    )  # not resolved yet - constructing the client made no AWS call
    assert client.remote_write_url == (
        f"https://aps-workspaces.{REGION}.amazonaws.com"
        f"/workspaces/{WORKSPACE_ID}/api/v1/remote_write"
    )


def test_push_resolves_workspace_alias_before_signing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    amp = FakeAmpApiClient(
        pages=[{"workspaces": [{"workspaceId": WORKSPACE_ID, "alias": ALIAS}]}],
    )
    posted: dict[str, Any] = {}

    def fake_post(url: str, data: bytes, headers: dict, timeout: float) -> FakeResponse:
        posted.update(url=url, data=data, headers=headers, timeout=timeout)
        return FakeResponse(status_code=200)

    monkeypatch.setattr("amp_push.client.requests.post", fake_post)

    client = AMPClient(
        workspace_alias=ALIAS,
        region=REGION,
        session=FakeSession(FakeCredentials(), amp_client=amp),
    )

    client.push([METRIC])

    assert posted["url"] == (
        f"https://aps-workspaces.{REGION}.amazonaws.com"
        f"/workspaces/{WORKSPACE_ID}/api/v1/remote_write"
    )
