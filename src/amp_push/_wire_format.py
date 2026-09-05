"""Encodes Metrics as a Prometheus remote_write WriteRequest.

Hand-rolled rather than generated from remote.proto/types.proto with protoc:
the message shapes below are the whole of what remote_write 1.0 needs
(https://prometheus.io/docs/specs/prw/remote_write_spec/#protocol), have been
stable for years, and encoding them by hand avoids taking a protobuf codegen
toolchain as a dependency of this small library. The output is verified
byte-for-byte against messages built with the real `protobuf` runtime in
tests/test_wire_format.py.

    message WriteRequest {
      repeated TimeSeries timeseries = 1;
    }
    message TimeSeries {
      repeated Label labels = 1;
      repeated Sample samples = 2;
    }
    message Label {
      string name = 1;
      string value = 2;
    }
    message Sample {
      double value = 1;
      int64 timestamp = 2;
    }

Do not change a field number below without re-verifying against the spec -
getting one wrong does not raise an error, it silently corrupts every metric
sent. Private to amp_push - not part of its public API.
"""

from __future__ import annotations

import struct

# Kept as a normal import rather than TYPE_CHECKING-only: Metric is a tiny,
# dependency-free module, and a `if TYPE_CHECKING:` split isn't worth the
# extra indirection just to satisfy a lint rule.
from amp_push.metric import Metric  # noqa: TC001

_WIRE_TYPE_VARINT = 0
_WIRE_TYPE_64BIT = 1
_WIRE_TYPE_LENGTH_DELIMITED = 2

_LABEL_FIELD_NUMBER = 1
_SAMPLE_FIELD_NUMBER = 2
_TIMESERIES_FIELD_NUMBER = 1

_LABEL_NAME_FIELD_NUMBER = 1
_LABEL_VALUE_FIELD_NUMBER = 2
_SAMPLE_VALUE_FIELD_NUMBER = 1
_SAMPLE_TIMESTAMP_FIELD_NUMBER = 2


def _encode_varint(value: int) -> bytes:
    """Encode a non-negative int as a protobuf base-128 varint."""
    if value < 0:
        message = f"varint must be non-negative, got {value}"
        raise ValueError(message)

    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _encode_tag(field_number: int, wire_type: int) -> bytes:
    return _encode_varint((field_number << 3) | wire_type)


def _encode_length_delimited(field_number: int, data: bytes) -> bytes:
    tag = _encode_tag(field_number, _WIRE_TYPE_LENGTH_DELIMITED)
    return tag + _encode_varint(len(data)) + data


def _encode_string_field(field_number: int, value: str) -> bytes:
    return _encode_length_delimited(field_number, value.encode("utf-8"))


def _encode_double_field(field_number: int, value: float) -> bytes:
    return _encode_tag(field_number, _WIRE_TYPE_64BIT) + struct.pack("<d", value)


def _encode_varint_field(field_number: int, value: int) -> bytes:
    return _encode_tag(field_number, _WIRE_TYPE_VARINT) + _encode_varint(value)


def _encode_label(name: str, value: str) -> bytes:
    return _encode_string_field(_LABEL_NAME_FIELD_NUMBER, name) + _encode_string_field(
        _LABEL_VALUE_FIELD_NUMBER,
        value,
    )


def _encode_sample(value: float, timestamp_millis: int) -> bytes:
    value_field = _encode_double_field(_SAMPLE_VALUE_FIELD_NUMBER, value)
    timestamp_field = _encode_varint_field(
        _SAMPLE_TIMESTAMP_FIELD_NUMBER,
        timestamp_millis,
    )
    return value_field + timestamp_field


def _encode_timeseries(metric: Metric) -> bytes:
    out = bytearray()
    for label_name, label_value in metric.wire_labels().items():
        label = _encode_label(label_name, label_value)
        out += _encode_length_delimited(_LABEL_FIELD_NUMBER, label)
    out += _encode_length_delimited(
        _SAMPLE_FIELD_NUMBER,
        _encode_sample(metric.value, metric.timestamp_millis()),
    )
    return bytes(out)


def encode_write_request(metrics: list[Metric]) -> bytes:
    """Serialise metrics as a WriteRequest protobuf message.

    Each metric becomes its own single-sample TimeSeries. Compress the
    result with raw-format (not framed) Snappy before sending it - the
    remote_write spec requires both.
    """
    out = bytearray()
    for metric in metrics:
        timeseries = _encode_timeseries(metric)
        out += _encode_length_delimited(_TIMESERIES_FIELD_NUMBER, timeseries)
    return bytes(out)
