"""Unit tests for amp_push.Metric."""

import pytest

from amp_push import Metric


def test_wire_labels_includes_dunder_name_and_is_sorted() -> None:
    metric = Metric("my_total", 1.0, labels={"zzz": "1", "aaa": "2"})

    assert list(metric.wire_labels().items()) == [
        ("__name__", "my_total"),
        ("aaa", "2"),
        ("zzz", "1"),
    ]


def test_timestamp_defaults_to_now() -> None:
    year_2020_millis = 1_577_836_800_000
    metric = Metric("my_total", 1.0)

    # Loose sanity bound rather than freezing time.
    assert metric.timestamp_millis() > year_2020_millis


@pytest.mark.parametrize("name", ["1_leading_digit", "has a space", "has-a-dash", ""])
def test_rejects_an_invalid_metric_name(name: str) -> None:
    with pytest.raises(ValueError, match="Invalid metric name"):
        Metric(name, 1.0)


def test_accepts_colons_in_a_metric_name() -> None:
    name = "namespace:my_metric:rate"
    assert Metric(name, 1.0).name == name


@pytest.mark.parametrize("label_name", ["1_leading_digit", "has-a-dash", "has a space"])
def test_rejects_an_invalid_label_name(label_name: str) -> None:
    with pytest.raises(ValueError, match="Invalid label name"):
        Metric("my_total", 1.0, labels={label_name: "value"})


def test_rejects_an_empty_label_value() -> None:
    with pytest.raises(ValueError, match="empty value"):
        Metric("my_total", 1.0, labels={"job": ""})


def test_rejects_dunder_name_as_an_explicit_label() -> None:
    with pytest.raises(ValueError, match="__name__"):
        Metric("my_total", 1.0, labels={"__name__": "clobber"})


def test_matches_the_documented_usage_example() -> None:
    duration_seconds = 12.4
    labels = {"job": "etl-daily"}
    metric = Metric("job_duration_seconds", duration_seconds, labels=labels)

    assert metric.name == "job_duration_seconds"
    assert metric.value == duration_seconds
    assert metric.labels == labels
