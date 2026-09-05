# amp_push

[![Tests](https://github.com/philhendren/amp_push/actions/workflows/tests.yml/badge.svg)](https://github.com/philhendren/amp_push/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/amp_push)](https://pypi.org/project/amp_push/)
[![Documentation Status](https://app.readthedocs.org/projects/amp-push/badge/?version=stable)](https://amp-push.readthedocs.io/en/stable/)

A small, dependency-light client for pushing metrics to
[AWS Managed Prometheus](https://aws.amazon.com/prometheus/) (AMP) via
SigV4-signed [Prometheus `remote_write`](https://prometheus.io/docs/specs/prw/remote_write_spec/).

For callers that want to send a handful of metrics directly - a CI job, a
one-off script, a Lambda - without standing up a collector or a sidecar.

Full docs (installation, quickstart, API reference): **https://amp-push.readthedocs.io/**

## Why amp_push

The normal way to get metrics into AMP is to run something that speaks
`remote_write` continuously: the ADOT/OpenTelemetry Collector, a Prometheus
server, a sidecar scraping `/metrics` off your process. That's the right
call when you have a long-running service and want it continuously scraped.

It's a lot of moving parts for the other case: something that runs briefly,
emits a handful of data points, and exits - a Lambda invocation, a CI job, a
cron script on a box that isn't otherwise running anything. There's no
`/metrics` endpoint for anyone to scrape, because there's no process left to
scrape it from by the time anyone would look. Standing up a collector to
receive a push from one process, for a few data points, isn't proportionate
to the job.

`amp_push` is for that gap: call `client.push([...])` at the point in your
code where something worth measuring just happened, and it's in AMP a
network round-trip later. No local aggregation, no background thread, no
extra thing to deploy or keep running - just one signed HTTP POST.

### Example use cases

*(Illustrative scenarios below - not real deployments, just the shape of
problem `amp_push` fits.)*

- **A nightly ETL Lambda.** `etl-daily` runs once a night, processes a batch
  of records, and exits. It has no business running a metrics sidecar for
  the two minutes it's alive - it just calls `client.push(...)` with
  `job_duration_seconds` and `rows_processed` right before returning, so the
  run shows up in the same Grafana dashboards as everything else.
- **A CI test suite.** A GitHub Actions job pushes `test_suite_duration_seconds`
  and `tests_failed_total` (labelled by branch) at the end of every run, so a
  team can graph flakiness and runtime creep over weeks without instrumenting
  a long-lived exporter anywhere - the runner doesn't exist after the job ends.
- **A one-off backfill script.** An engineer runs a migration script from
  their laptop against an assumed IAM role, and it reports
  `rows_migrated_total` once at the end - useful signal for "did this
  actually run to completion", without setting up anything that outlives the
  script.
- **An image-processing Lambda.** Each invocation resizes one uploaded image
  and increments `images_processed_total` or `images_failed_total` before
  returning - one metric push per invocation, no collector layer added to
  every function in the pipeline just to get a failure count.

## Installation

```bash
uv add amp_push
# or
pip install amp_push
```

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

## Documentation

The full docs (installation, quickstart, use cases, API reference) are
published at **https://amp-push.readthedocs.io/**, built with
[Sphinx](https://www.sphinx-doc.org/) from [`docs/`](docs/) via
[`.readthedocs.yaml`](.readthedocs.yaml) - rebuilt automatically on every
push to `main`. To build them locally instead:

```bash
$ uv sync --all-extras
$ uv run sphinx-build -b html docs docs/_build/html
# then open docs/_build/html/index.html
```

## Development

```bash
# Install dependencies (including dev/test extras)
$ uv sync --all-extras

# Run the tests
$ uv run pytest

# With coverage
$ uv run pytest --cov=amp_push
```

## License

[MIT](LICENSE) - Copyright (c) 2026 Phil Hendren.
