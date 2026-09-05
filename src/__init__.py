"""amp_push: a small client for pushing metrics to AWS Managed Prometheus.

    from amp_push import AMPClient, Metric

    client = AMPClient(workspace_id="ws-xxxx", region="us-east-1")
    client.push([
        Metric("job_duration_seconds", 12.4, labels={"job": "etl-daily"}),
    ])

No sidecar, no collector - just SigV4-signed Prometheus remote_write over
HTTP (via boto3 for signing), for callers that want to send a handful of
metrics directly. Deliberately self-contained (no dependency on the rest of
this repo) so it can be lifted out as its own package later.
"""

from amp_push.client import AMPClient
from amp_push.metric import Metric

__all__ = ["AMPClient", "Metric"]
