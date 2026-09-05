"""Tests for the push_metric example CLI.

Self-contained alongside push_metric.py: no fixtures or helpers from
tests/ elsewhere in this repo, and AMPClient.push is faked out rather than
touching AWS or the network.
"""

from typing import ClassVar

import pytest
import requests
from click.testing import CliRunner, Result
from push_metric import push_metric

from amp_push import Metric

BASE_ARGS = [
    "--workspace-id",
    "ws-abc123",
    "--region",
    "eu-west-2",
    "--metric-name",
    "job_duration_seconds",
]

DURATION_SECONDS = 12.4
CUSTOM_TIMEOUT = 3.5


RESOLVED_WORKSPACE_ID = "ws-resolved-from-alias"


class FakeAMPClient:
    """Records what it was asked to push, or raises what the test wants.

    Mirrors AMPClient's own workspace_id/workspace_alias validation (raise
    ValueError for both/neither at construction) so tests can exercise how
    push_metric.py surfaces that as a CLI error, without touching the real
    client or AWS.
    """

    instances: ClassVar[list["FakeAMPClient"]] = []
    error: Exception | None = None

    def __init__(self, **kwargs: object) -> None:
        workspace_id = kwargs.get("workspace_id")
        workspace_alias = kwargs.get("workspace_alias")
        if bool(workspace_id) == bool(workspace_alias):
            message = (
                "Pass exactly one of workspace_id or workspace_alias, got "
                f"workspace_id={workspace_id!r}, workspace_alias={workspace_alias!r}."
            )
            raise ValueError(message)
        self.kwargs = kwargs
        self.pushed: list[Metric] = []
        # Real AMPClient only resolves an alias lazily, on first use - a
        # fixed stand-in is enough here since these tests aren't exercising
        # that resolution itself (see tests/test_client.py for that).
        self.workspace_id = workspace_id or RESOLVED_WORKSPACE_ID
        FakeAMPClient.instances.append(self)

    def push(self, metrics: list[Metric]) -> None:
        if FakeAMPClient.error is not None:
            raise FakeAMPClient.error
        self.pushed.extend(metrics)


@pytest.fixture(autouse=True)
def _reset_fake_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install FakeAMPClient in place of the real one for every test."""
    FakeAMPClient.instances = []
    FakeAMPClient.error = None
    monkeypatch.setattr("push_metric.AMPClient", FakeAMPClient)
    # So tests of the workspace-id/workspace-alias requirement aren't at the
    # mercy of whatever happens to be set in the developer's/CI's shell.
    monkeypatch.delenv("AMP_WORKSPACE_ID", raising=False)
    monkeypatch.delenv("AMP_WORKSPACE_ALIAS", raising=False)


def run(args: list[str]) -> Result:
    return CliRunner().invoke(push_metric, args)


def test_pushes_a_metric_with_no_labels() -> None:
    result = run([*BASE_ARGS, "--value", str(DURATION_SECONDS)])

    assert result.exit_code == 0, result.output
    pushed = FakeAMPClient.instances[0].pushed
    assert len(pushed) == 1
    assert pushed[0].name == "job_duration_seconds"
    assert pushed[0].value == DURATION_SECONDS
    assert pushed[0].labels == {}


def test_pushes_a_metric_with_labels() -> None:
    result = run([*BASE_ARGS, "--label", "job=etl-daily", "--label", "outcome=success"])

    assert result.exit_code == 0, result.output
    pushed = FakeAMPClient.instances[0].pushed[0]
    assert pushed.labels == {"job": "etl-daily", "outcome": "success"}


def test_value_defaults_to_one() -> None:
    run(BASE_ARGS)

    assert FakeAMPClient.instances[0].pushed[0].value == 1.0


def test_wires_workspace_id_region_and_timeout_to_the_client() -> None:
    run([*BASE_ARGS, "--timeout", str(CUSTOM_TIMEOUT)])

    kwargs = FakeAMPClient.instances[0].kwargs
    assert kwargs["workspace_id"] == "ws-abc123"
    assert kwargs["region"] == "eu-west-2"
    assert kwargs["timeout"] == CUSTOM_TIMEOUT


def test_reads_workspace_id_and_region_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AMP_WORKSPACE_ID", "ws-from-env")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    result = run(["--metric-name", "job_duration_seconds"])

    assert result.exit_code == 0, result.output
    kwargs = FakeAMPClient.instances[0].kwargs
    assert kwargs["workspace_id"] == "ws-from-env"
    assert kwargs["region"] == "us-east-1"


def test_rejects_a_malformed_label() -> None:
    result = run([*BASE_ARGS, "--label", "not-a-key-value-pair"])

    assert result.exit_code != 0
    assert "KEY=VALUE" in result.output


def test_rejects_an_invalid_metric_name() -> None:
    result = run(
        [
            "--workspace-id",
            "ws-abc123",
            "--region",
            "eu-west-2",
            "--metric-name",
            "not a valid name",
        ],
    )

    assert result.exit_code != 0
    assert "Invalid metric" in result.output


def test_reports_missing_credentials_as_a_clean_error() -> None:
    FakeAMPClient.error = RuntimeError("No AWS credentials available.")

    result = run(BASE_ARGS)

    assert result.exit_code != 0
    assert "No AWS credentials available" in result.output


def test_reports_an_http_error_as_a_clean_error() -> None:
    FakeAMPClient.error = requests.HTTPError("403: AccessDenied")

    result = run(BASE_ARGS)

    assert result.exit_code != 0
    assert "Failed to push to AMP" in result.output
    assert "403" in result.output


def test_prints_a_success_message() -> None:
    result = run([*BASE_ARGS, "--label", "outcome=success"])

    assert result.exit_code == 0, result.output
    assert "Pushed job_duration_seconds" in result.output
    assert "ws-abc123" in result.output


# --- --workspace-alias -----------------------------------------------------

ALIAS_ARGS = [
    "--workspace-alias",
    "prod-services",
    "--region",
    "eu-west-2",
    "--metric-name",
    "job_duration_seconds",
]


def test_pushes_a_metric_using_workspace_alias() -> None:
    result = run([*ALIAS_ARGS, "--value", str(DURATION_SECONDS)])

    assert result.exit_code == 0, result.output
    kwargs = FakeAMPClient.instances[0].kwargs
    assert kwargs["workspace_id"] is None
    assert kwargs["workspace_alias"] == "prod-services"


def test_reports_the_resolved_workspace_id_after_pushing_via_alias() -> None:
    result = run(ALIAS_ARGS)

    assert result.exit_code == 0, result.output
    assert RESOLVED_WORKSPACE_ID in result.output


def test_reads_workspace_alias_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AMP_WORKSPACE_ALIAS", "prod-services")

    result = run(["--region", "eu-west-2", "--metric-name", "job_duration_seconds"])

    assert result.exit_code == 0, result.output
    kwargs = FakeAMPClient.instances[0].kwargs
    assert kwargs["workspace_alias"] == "prod-services"


def test_rejects_both_workspace_id_and_workspace_alias() -> None:
    result = run([*BASE_ARGS, "--workspace-alias", "prod-services"])

    assert result.exit_code != 0
    assert "exactly one" in result.output


def test_rejects_neither_workspace_id_nor_workspace_alias() -> None:
    result = run(["--region", "eu-west-2", "--metric-name", "job_duration_seconds"])

    assert result.exit_code != 0
    assert "exactly one" in result.output


def test_reports_an_alias_resolution_failure_as_a_clean_error() -> None:
    FakeAMPClient.error = ValueError(
        "No AMP workspace found with alias 'prod-services'."
    )

    result = run(ALIAS_ARGS)

    assert result.exit_code != 0
    assert "No AMP workspace found with alias" in result.output
