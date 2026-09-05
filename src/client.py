"""AMPClient: push Metrics to an AWS Managed Prometheus workspace."""

from __future__ import annotations

import boto3
import cramjam
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

from amp_push._wire_format import encode_write_request

# Kept as a normal import rather than TYPE_CHECKING-only: Metric is a tiny,
# dependency-free module, and a `if TYPE_CHECKING:` split isn't worth the
# extra indirection just to satisfy a lint rule.
from amp_push.metric import Metric  # noqa: TC001

# https://docs.aws.amazon.com/prometheus/latest/userguide/AMP-and-IAM.html -
# the SigV4 signing name for Amazon Managed Service for Prometheus is "aps".
_SIGV4_SERVICE_NAME = "aps"
_REMOTE_WRITE_SPEC_VERSION = "0.1.0"
_USER_AGENT = "amp-push/0.1"
_DEFAULT_TIMEOUT_SECONDS = 10.0


class AMPClient:
    """A small client for pushing Metrics to AWS Managed Prometheus.

        client = AMPClient(workspace_id="ws-xxxx", region="us-east-1")
        client.push([Metric("job_duration_seconds", 12.4, labels={"job": "etl-daily"})])

    For sending a handful of metrics directly over SigV4-signed Prometheus
    remote_write - no collector, no sidecar. Credentials are resolved through
    boto3's normal credential chain (env vars, shared config, an assumed
    role, ...); pass `session` to control that explicitly. Whichever
    credentials are used need `aps:RemoteWrite` on the target workspace.

    Pass `workspace_alias` instead of `workspace_id` if you only know the
    workspace's alias, not its id - it's looked up via `amp:ListWorkspaces`
    the first time it's needed (and cached), which needs its own IAM
    permission separate from `aps:RemoteWrite` - see the README. Exactly one
    of `workspace_id`/`workspace_alias` must be given.
    """

    def __init__(
        self,
        *,
        workspace_id: str | None = None,
        workspace_alias: str | None = None,
        region: str,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        session: boto3.Session | None = None,
    ) -> None:
        """Initialize with the target workspace (id or alias) and its AWS region.

        Exactly one of `workspace_id` or `workspace_alias` must be given -
        raises ValueError for both or neither. Resolving an alias makes no
        AWS call here; it happens lazily, the first time the id is actually
        needed (`remote_write_url`/`push`).
        """
        if bool(workspace_id) == bool(workspace_alias):
            message = (
                "Pass exactly one of workspace_id or workspace_alias, got "
                f"workspace_id={workspace_id!r}, workspace_alias={workspace_alias!r}."
            )
            raise ValueError(message)
        self._workspace_id = workspace_id
        self._workspace_alias = workspace_alias
        self.region = region
        self.timeout = timeout
        self._session = session or boto3.Session()

    @property
    def workspace_id(self) -> str:
        """The target workspace id, resolving `workspace_alias` on first use."""
        if self._workspace_id is None:
            self._workspace_id = self._resolve_workspace_id_by_alias()
        return self._workspace_id

    def _resolve_workspace_id_by_alias(self) -> str:
        """Look up a workspace id by its exact alias, via `amp:ListWorkspaces`.

        AMP's own `alias` filter matches workspaces whose alias *starts
        with* the value given - not an exact match - so results are
        filtered again here. Paginates via `nextToken` in case more than
        one page of workspaces share that prefix. Raises ValueError if zero
        or more than one workspace has that exact alias.
        """
        amp = self._session.client("amp", region_name=self.region)
        matches = []
        next_token = None
        while True:
            kwargs = {"alias": self._workspace_alias}
            if next_token:
                kwargs["nextToken"] = next_token
            response = amp.list_workspaces(**kwargs)
            matches.extend(
                workspace
                for workspace in response["workspaces"]
                if workspace.get("alias") == self._workspace_alias
            )
            next_token = response.get("nextToken")
            if not next_token:
                break

        if not matches:
            message = f"No AMP workspace found with alias {self._workspace_alias!r}."
            raise ValueError(message)
        if len(matches) > 1:
            ids = ", ".join(workspace["workspaceId"] for workspace in matches)
            message = (
                f"Multiple AMP workspaces have alias {self._workspace_alias!r}: {ids}. "
                "Pass workspace_id instead to disambiguate."
            )
            raise ValueError(message)
        return matches[0]["workspaceId"]

    @property
    def remote_write_url(self) -> str:
        """The workspace's Prometheus remote_write endpoint."""
        return (
            f"https://aps-workspaces.{self.region}.amazonaws.com"
            f"/workspaces/{self.workspace_id}/api/v1/remote_write"
        )

    def push(self, metrics: list[Metric]) -> None:
        """Push metrics to AWS Managed Prometheus. No-op for an empty list.

        Raises whatever botocore raises if no credentials can be found
        (e.g. botocore.exceptions.NoCredentialsError), and
        requests.HTTPError if AMP rejects the request (unknown workspace,
        missing permission, malformed body, ...).
        """
        if not metrics:
            return

        credentials = self._session.get_credentials()
        if credentials is None:
            message = "No AWS credentials available to sign the remote_write request."
            raise RuntimeError(message)

        body = bytes(cramjam.snappy.compress_raw(encode_write_request(metrics)))

        request = AWSRequest(
            method="POST",
            url=self.remote_write_url,
            data=body,
            headers={
                "Content-Encoding": "snappy",
                "Content-Type": "application/x-protobuf",
                "X-Prometheus-Remote-Write-Version": _REMOTE_WRITE_SPEC_VERSION,
                "User-Agent": _USER_AGENT,
            },
        )
        signer = SigV4Auth(
            credentials.get_frozen_credentials(),
            _SIGV4_SERVICE_NAME,
            self.region,
        )
        signer.add_auth(request)

        response = requests.post(
            self.remote_write_url,
            data=body,
            headers=dict(request.headers),
            timeout=self.timeout,
        )
        response.raise_for_status()
