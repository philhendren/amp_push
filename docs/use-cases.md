# Use cases

```{note}
The scenarios below are illustrative, not real deployments - fabricated
examples to show the shape of problem `amp_push` fits: something short-lived
that wants to report a handful of numbers, without justifying a metrics
pipeline of its own.
```

## A nightly ETL Lambda

`etl-daily` runs once a night on a schedule, processes a batch of records,
and exits within a couple of minutes. It has no business running a metrics
sidecar for that lifetime - it just reports how long it took and how much
it did, right before returning:

```python
import time

from amp_push import AMPClient, Metric

client = AMPClient(workspace_alias="prod-observability", region="eu-west-2")

start = time.monotonic()
rows_processed = run_etl_batch()  # however this job actually does its work
duration = time.monotonic() - start

client.push([
    Metric("job_duration_seconds", duration, labels={"job": "etl-daily"}),
    Metric("rows_processed_total", rows_processed, labels={"job": "etl-daily"}),
])
```

The run shows up in the same Grafana dashboards as everything else scraped
continuously - `amp_push` doesn't care that nothing was running to scrape a
minute earlier.

## A CI test suite

A GitHub Actions job pushes suite duration and failure count at the end of
every run, labelled by branch, so a team can graph flakiness and runtime
creep over weeks:

```python
from amp_push import AMPClient, Metric

client = AMPClient(workspace_id="ws-abc123", region="eu-west-2")

client.push([
    Metric(
        "test_suite_duration_seconds",
        suite_duration_seconds,
        labels={"branch": current_branch, "outcome": "success" if passed else "failure"},
    ),
    Metric(
        "tests_failed_total",
        failed_count,
        labels={"branch": current_branch},
    ),
])
```

The runner doesn't exist by the time anyone would go looking for it -
there's nothing left to scrape a `/metrics` endpoint from after the job
finishes, so pushing at the end is the only option that works at all.

## A one-off backfill script

An engineer runs a migration script from their laptop against an assumed
IAM role, and it reports how many rows it moved once at the end - useful
signal for "did this actually run to completion" without setting up
anything that outlives the script:

```python
import boto3

from amp_push import AMPClient, Metric

session = boto3.Session(profile_name="prod-migration")
client = AMPClient(workspace_id="ws-abc123", region="us-east-1", session=session)

rows_migrated = run_backfill()

client.push([Metric("rows_migrated_total", rows_migrated, labels={"script": "2026-09-backfill"})])
```

## An image-processing Lambda

Each invocation resizes one uploaded image and reports whether it succeeded
- one metric push per invocation, no collector layer added to every
function in the pipeline just to get a failure count:

```python
from amp_push import AMPClient, Metric

client = AMPClient(workspace_id="ws-abc123", region="us-east-1")


def handler(event, context):
    try:
        resize_image(event["bucket"], event["key"])
    except Exception:
        client.push([Metric("images_failed_total", 1.0, labels={"stage": "resize"})])
        raise
    client.push([Metric("images_processed_total", 1.0, labels={"stage": "resize"})])
```
