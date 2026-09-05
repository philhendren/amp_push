"""The Metric type amp_push pushes to AWS Managed Prometheus."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

# https://prometheus.io/docs/specs/prw/remote_write_spec/#labels
# Metric names may additionally contain `:`; label names may not.
_METRIC_NAME_RE = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
_LABEL_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


@dataclass(frozen=True)
class Metric:
    """One Prometheus sample: a metric name, its value, and optional labels.

        Metric("job_duration_seconds", 12.4, labels={"job": "etl-daily"})

    Each push is a single point at `timestamp` (defaulting to now), not a
    locally-accumulated running counter - push the same metric repeatedly and
    query with `sum(...)` or `count_over_time(...)` over a range, not
    `rate()`/`increase()`, which assume one process incrementing a series
    continuously.
    """

    name: str
    value: float
    labels: dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate the metric and label names against the remote_write spec."""
        if not _METRIC_NAME_RE.match(self.name):
            message = (
                f"Invalid metric name {self.name!r}: "
                f"must match {_METRIC_NAME_RE.pattern}"
            )
            raise ValueError(message)

        for label_name, label_value in self.labels.items():
            if label_name == "__name__":
                message = "__name__ is set from `name`, not `labels`"
                raise ValueError(message)
            if not _LABEL_NAME_RE.match(label_name):
                message = (
                    f"Invalid label name {label_name!r}: "
                    f"must match {_LABEL_NAME_RE.pattern}"
                )
                raise ValueError(message)
            if not label_value:
                message = f"Label {label_name!r} has an empty value; omit it instead"
                raise ValueError(message)

    def wire_labels(self) -> dict[str, str]:
        """Labels plus `__name__`, sorted by name as remote_write requires."""
        return dict(sorted({"__name__": self.name, **self.labels}.items()))

    def timestamp_millis(self) -> int:
        """Timestamp as int64 milliseconds since the Unix epoch, per the spec."""
        return int(self.timestamp.timestamp() * 1000)
