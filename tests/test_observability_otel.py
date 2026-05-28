"""Conformance tests for OpenTelemetryMetrics (issue #23).

Skips entirely when opentelemetry-sdk isn't installed — the package must import
and function without the optional dependency.
"""
from __future__ import annotations

import pytest

from activegraph.observability.metrics import METRIC_NAMES, Metrics
from activegraph.observability.otel import OpenTelemetryMetrics


def _otel_or_skip():
    if not OpenTelemetryMetrics.available():
        pytest.skip("opentelemetry-sdk not installed")
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader

    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    return OpenTelemetryMetrics(meter_provider=provider), reader


def test_available_returns_bool():
    assert isinstance(OpenTelemetryMetrics.available(), bool)


def test_satisfies_metrics_protocol():
    m, _ = _otel_or_skip()
    assert isinstance(m, Metrics)  # runtime_checkable Protocol


def test_every_standard_metric_records_without_raising():
    m, _ = _otel_or_skip()
    for spec in METRIC_NAMES:
        tags = {k: "x" for k in spec.tags}
        if spec.kind == "counter":
            m.counter(spec.name, tags, 1.0)
        elif spec.kind == "histogram":
            m.histogram(spec.name, tags, 1.5)
        elif spec.kind == "gauge":
            m.gauge(spec.name, tags, 2.0)
        else:
            pytest.fail(f"unknown kind {spec.kind} for {spec.name}")


def test_recorded_points_appear_in_reader():
    m, reader = _otel_or_skip()
    m.counter("activegraph_events_emitted_total", {"event_type": "demo"}, 3.0)
    m.histogram("activegraph_llm_cost_usd", {"model": "claude-opus-4-8"}, 0.42)
    data = reader.get_metrics_data()
    names = set()
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                names.add(metric.name)
    assert "activegraph_events_emitted_total" in names
    assert "activegraph_llm_cost_usd" in names


def test_tolerates_unknown_name_and_tags():
    m, _ = _otel_or_skip()
    # Must not raise on names/tags outside the standard table.
    m.counter("totally_unknown_metric", {"weird_tag": "v", "another": "z"}, 1.0)
    m.histogram("another_unknown", {}, 9.9)
    m.gauge("unknown_gauge", {"k": "v"}, 1.0)
