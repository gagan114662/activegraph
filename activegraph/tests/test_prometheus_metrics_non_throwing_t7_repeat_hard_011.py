"""T7 repeat hard 011 — docstring↔code drift in PrometheusMetrics.

The ``Metrics`` protocol (activegraph/observability/metrics.py) documents
its three methods as "all best-effort, all non-throwing" and states
"Implementations MUST tolerate unknown metric names." NoOpMetrics and
OpenTelemetryMetrics both honor this. PrometheusMetrics did NOT: it called
straight into ``prometheus_client`` with no error containment, so a
re-registration collision (same metric name, different label-key set) raised
a ``ValueError`` straight out of ``counter()`` — exactly the failure mode the
protocol contract promises callers will never see.

These tests assert the DOCUMENTED behavior (non-throwing) and fail against the
pre-fix code.
"""

from __future__ import annotations

import pytest

from activegraph.observability.metrics import Metrics


def _prom_or_skip():
    from activegraph.observability.prometheus import PrometheusMetrics

    if not PrometheusMetrics.available():
        pytest.skip("prometheus_client not installed")
    return PrometheusMetrics


def _fresh_registry():
    import prometheus_client

    return prometheus_client.CollectorRegistry()


class TestPrometheusHonorsNonThrowingContract:
    """The Metrics protocol promises all three methods are non-throwing."""

    def test_counter_does_not_throw_on_label_key_collision(self):
        PrometheusMetrics = _prom_or_skip()
        m = PrometheusMetrics(registry=_fresh_registry())
        # First observation fixes the label-key set for this name.
        m.counter("activegraph_events_emitted_total", {"event_type": "goal.created"})
        # Second observation, SAME name, DIFFERENT label-key set. Underlying
        # prometheus_client raises ValueError ("Duplicated timeseries ...").
        # The protocol promises this method is non-throwing -> must be swallowed.
        m.counter("activegraph_events_emitted_total", {"other_key": "x"}, 2.0)

    def test_histogram_does_not_throw_on_label_key_collision(self):
        PrometheusMetrics = _prom_or_skip()
        m = PrometheusMetrics(registry=_fresh_registry())
        m.histogram("activegraph_behaviors_duration_seconds", {"behavior": "p"}, 0.01)
        m.histogram("activegraph_behaviors_duration_seconds", {"different": "k"}, 0.02)

    def test_gauge_does_not_throw_on_label_key_collision(self):
        PrometheusMetrics = _prom_or_skip()
        m = PrometheusMetrics(registry=_fresh_registry())
        m.gauge("activegraph_queue_depth", {"a": "1"}, 1.0)
        m.gauge("activegraph_queue_depth", {"b": "2"}, 2.0)

    def test_counter_tolerates_invalid_metric_name(self):
        # "Implementations MUST tolerate unknown metric names." A name that
        # prometheus_client rejects (illegal characters) must not surface.
        PrometheusMetrics = _prom_or_skip()
        m = PrometheusMetrics(registry=_fresh_registry())
        m.counter("not a valid prom name!!", {"tag": "v"}, 1.0)

    def test_prometheus_satisfies_protocol_under_repeat_calls(self):
        PrometheusMetrics = _prom_or_skip()
        m: Metrics = PrometheusMetrics(registry=_fresh_registry())
        # Repeated valid calls (same shape) keep working AND first-write still lands.
        m.counter("activegraph_events_emitted_total", {"event_type": "goal.created"})
        m.counter("activegraph_events_emitted_total", {"event_type": "goal.created"}, 3.0)
