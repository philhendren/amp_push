# amp_push

A small, dependency-light client for pushing metrics to
[AWS Managed Prometheus](https://aws.amazon.com/prometheus/) (AMP) via
SigV4-signed [Prometheus `remote_write`](https://prometheus.io/docs/specs/prw/remote_write_spec/).

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

See [Use cases](use-cases.md) for the shape of problem this fits, or jump
straight to [Installation](installation.md) and [Quickstart](usage.md).

```{toctree}
:maxdepth: 2
:caption: Contents

installation
usage
use-cases
api
```
