"""Verifies the hand-rolled wire encoder against a real protobuf runtime.

tests/amp_push/fixtures/remote_write_reference_pb2.py is protoc-generated
from the same four message shapes documented in src/amp_push/_wire_format.py,
and used here only as a ground truth - the runtime code does not depend on
protobuf at all. See that module's docstring for why encoding is hand-rolled
rather than generated.
"""

from datetime import UTC, datetime

import pytest

from amp_push._wire_format import encode_write_request
from amp_push.metric import Metric
from tests.amp_push.fixtures import remote_write_reference_pb2 as reference_pb2


def reference_bytes(metrics: list[Metric]) -> bytes:
    """Serialise the same metrics with the real protobuf runtime."""
    write_request = reference_pb2.WriteRequest()
    for metric in metrics:
        timeseries = write_request.timeseries.add()
        for name, value in metric.wire_labels().items():
            timeseries.labels.add(name=name, value=value)
        sample = timeseries.samples.add()
        sample.value = metric.value
        sample.timestamp = metric.timestamp_millis()
    return write_request.SerializeToString()


def test_matches_the_real_protobuf_runtime_for_one_metric() -> None:
    metrics = [
        Metric(
            "job_duration_seconds",
            12.4,
            labels={"job": "etl-daily", "outcome": "success"},
        ),
    ]

    assert encode_write_request(metrics) == reference_bytes(metrics)


def test_matches_the_real_protobuf_runtime_for_several_metrics() -> None:
    metrics = [
        Metric("a_total", 1.0, labels={"outcome": "success"}),
        Metric("b_total", 2.0, labels={"outcome": "failure"}),
    ]

    assert encode_write_request(metrics) == reference_bytes(metrics)


def test_matches_the_real_protobuf_runtime_with_no_labels() -> None:
    metrics = [Metric("bare_metric_total", 1.0)]

    assert encode_write_request(metrics) == reference_bytes(metrics)


def test_matches_the_real_protobuf_runtime_with_unicode_label_values() -> None:
    metrics = [Metric("x_total", 1.0, labels={"note": "déployé — ok"})]

    assert encode_write_request(metrics) == reference_bytes(metrics)


def test_empty_write_request_is_empty_bytes() -> None:
    assert encode_write_request([]) == b""


def test_labels_are_sorted_lexicographically_including_dunder_name() -> None:
    # __name__ sorts before any lowercase label, so decoding the reference
    # bytes back out should show __name__ first regardless of insertion order.
    metric = Metric("z_total", 1.0, labels={"zzz": "1", "aaa": "2"})

    parsed = reference_pb2.WriteRequest()
    parsed.ParseFromString(encode_write_request([metric]))

    label_names = [label.name for label in parsed.timeseries[0].labels]
    assert label_names == sorted(label_names)
    assert label_names[0] == "__name__"


def test_rejects_a_pre_epoch_timestamp() -> None:
    # A pre-1970 timestamp would need a negative varint, which the encoder
    # deliberately doesn't support (see _encode_varint) - remote_write
    # timestamps are never legitimately negative.
    metric = Metric("x_total", 1.0, timestamp=datetime(1969, 1, 1, tzinfo=UTC))

    with pytest.raises(ValueError, match="non-negative"):
        encode_write_request([metric])
