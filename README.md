# amp_push

A small, dependency-light client for pushing metrics to
[AWS Managed Prometheus](https://aws.amazon.com/prometheus/) (AMP) via
SigV4-signed [Prometheus `remote_write`](https://prometheus.io/docs/specs/prw/remote_write_spec/).

For callers that want to send a handful of metrics directly - a CI job, a
one-off script, a Lambda - without standing up a collector or a sidecar.

## Usage

```python
from amp_push import AMPClient, Metric

client = AMPClient(workspace_id="ws-xxxx", region="us-east-1")
metric = Metric("job_duration_seconds", 12.4, labels={"job": "etl-daily"})
client.push([metric])
```

That's the whole API: one class, one type, one method.

### `Metric`

```python
Metric(name, value, labels={}, timestamp=datetime.now(UTC))
```

- `name` - the metric name (must match `[a-zA-Z_:][a-zA-Z0-9_:]*`).
- `value` - a `float`.
- `labels` - a `dict[str, str]`, optional. Label names must match
  `[a-zA-Z_][a-zA-Z0-9_]*`, and no value may be empty - omit a label rather
  than setting it to `""`. Don't set `__name__` yourself; it's derived from
  `name`.
- `timestamp` - a timezone-aware `datetime`, optional (defaults to now).

Invalid names/labels raise `ValueError` immediately, at construction time.

Each `Metric` you push is one isolated point at `timestamp`, not a
locally-accumulated running counter - `amp_push` doesn't track state between
calls. If you push the same metric name repeatedly (e.g. once per CI run),
query it in PromQL/Grafana with `sum(...)` or `count_over_time(...)` over the
range you care about, not `rate()`/`increase()`, which assume a single
process incrementing one series continuously.

### `AMPClient`

```python
AMPClient(*, workspace_id=None, workspace_alias=None, region, timeout=10.0, session=None)
```

All arguments are keyword-only.

- `workspace_id` - the AMP workspace to write to, e.g. `"ws-xxxx"`. Look
  this up yourself (console, `aws amp list-workspaces`, Terraform output,
  ...), or pass `workspace_alias` instead and let `amp_push` look it up.
- `workspace_alias` - the workspace's alias (e.g. `"prod-services"`)
  instead of its id. Resolved via `amp:ListWorkspaces` the first time the
  id is actually needed (`client.workspace_id`, `client.remote_write_url`,
  or `client.push(...)`) - not in the constructor - and cached on the
  client after that, so it's one extra API call per `AMPClient` instance,
  not per `push()`. Raises `ValueError` if no workspace has that exact
  alias, or if more than one does.
- Exactly one of `workspace_id`/`workspace_alias` must be given - passing
  both, or neither, raises `ValueError` immediately.
- `region` - the AWS region the workspace is in.
- `timeout` - request timeout in seconds for the HTTP POST.
- `session` - an existing `boto3.Session` to sign with, if you need to
  control credential resolution yourself (an assumed role, a named profile,
  ...). Defaults to `boto3.Session()`, which uses boto3's normal credential
  chain (environment variables, shared config/credentials files, an
  attached role, ...).

`client.push(metrics)`:

- Is a no-op for an empty list - no AWS calls, no HTTP request.
- Encodes `metrics` as a Prometheus `WriteRequest`, compresses it with raw
  (non-framed) Snappy, signs it with SigV4 for the `aps` service, and POSTs
  it to `client.remote_write_url`.
- Raises `RuntimeError` if no AWS credentials can be resolved from the
  session.
- Raises `requests.HTTPError` if AMP rejects the request (wrong workspace,
  missing `aps:RemoteWrite` permission, malformed body, ...), or another
  `requests.RequestException` on a network-level failure (timeout, DNS,
  connection refused, ...).

There's no retry logic and no batching beyond "one `WriteRequest` per
`push()` call" - keep it simple, and add that in the caller if you need it.

### Required IAM permission

Whatever credentials `AMPClient` signs with need `aps:RemoteWrite` on the
target workspace's ARN, e.g.:

```json
{
  "Effect": "Allow",
  "Action": "aps:RemoteWrite",
  "Resource": "arn:aws:aps:us-east-1:123456789012:workspace/ws-xxxx"
}
```

If you pass `workspace_alias` instead of `workspace_id`, the same
credentials also need `aps:ListWorkspaces` - that action doesn't support
resource-level scoping to one workspace, so it's granted on `"*"`:

```json
{
  "Effect": "Allow",
  "Action": "aps:ListWorkspaces",
  "Resource": "*"
}
```

> [!NOTE]
> `aps:ListWorkspaces` is a separate permission from `aps:RemoteWrite` and
> isn't implied by it. If a caller only has `aps:RemoteWrite`, alias
> resolution fails with an `AccessDenied` `ClientError` from
> `list_workspaces` until `aps:ListWorkspaces` is granted too. Passing
> `workspace_id` directly avoids needing this permission at all.

## Design notes

- **Hand-rolled protobuf encoding** (`_wire_format.py`, private). The four
  message shapes `remote_write` needs have been stable for years, so
  encoding them by hand avoids taking a `protoc` codegen toolchain as a
  dependency. Verified byte-for-byte against the real `protobuf` runtime in
  `tests/test_wire_format.py` (a dev-only dependency - it's not needed at
  runtime).
- **No custom exception hierarchy.** Errors surface as whatever boto3/
  botocore/`requests` already raise, plus one plain `RuntimeError` for "no
  credentials". Simple to reason about, nothing new to learn.

## Development

```bash
# Install dependencies (including dev/test extras)
$ uv sync --all-extras

# Run the tests
$ uv run pytest

# With coverage
$ uv run pytest --cov=amp_push
```
