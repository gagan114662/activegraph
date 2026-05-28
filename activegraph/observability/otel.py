"""OpenTelemetry Metrics implementation (issue #23).

Third implementation of the :class:`~activegraph.observability.metrics.Metrics`
protocol, alongside ``NoOpMetrics`` (default) and ``PrometheusMetrics``. Backed
by ``opentelemetry-sdk``, lazy-imported behind the ``[opentelemetry]`` extra.

Design decisions (locked in the Sofia spec for #23):
  * METRICS-ONLY — no traces/spans. Tracing is a separate concern.
  * Gauge → OTel synchronous ``Gauge`` when the SDK provides ``create_gauge``;
    otherwise an ``ObservableGauge`` backed by a last-value store.
  * Histogram buckets — left to the user's MeterProvider ``View`` config; this
    class records raw values and does not hard-code boundaries.
  * Naming — activegraph metric names pass through unchanged (same names across
    NoOp/Prometheus/OTel); ``tags`` map to OTel attributes verbatim.

All three methods are best-effort and non-throwing, per the Metrics protocol.
"""
from __future__ import annotations

from typing import Any


class OpenTelemetryMetrics:
    """Drop-in Metrics implementation backed by opentelemetry-sdk.

    Instruments are created lazily and cached by metric name (OTel applies
    attributes per-record, so unlike Prometheus the tag-key set need not be
    fixed at instrument creation). Pass a ``meter_provider`` to scope metrics to
    your own provider/reader; otherwise the global meter provider is used.
    """

    def __init__(self, meter_provider: Any | None = None, meter_name: str = "activegraph") -> None:
        otel = _require_otel()
        if meter_provider is not None:
            self._meter = meter_provider.get_meter(meter_name)
        else:
            self._meter = otel.get_meter(meter_name)
        self._counters: dict[str, Any] = {}
        self._histograms: dict[str, Any] = {}
        self._gauges: dict[str, Any] = {}
        # sync Gauge support varies by SDK version; fall back to ObservableGauge.
        self._has_sync_gauge = hasattr(self._meter, "create_gauge")
        self._gauge_values: dict[tuple, tuple[float, dict]] = {}

    @staticmethod
    def available() -> bool:
        try:
            import opentelemetry.sdk.metrics  # noqa: F401
        except ImportError:
            return False
        return True

    # ---- protocol ----

    def counter(self, name: str, tags: dict[str, str], value: float = 1.0) -> None:
        try:
            inst = self._counters.get(name)
            if inst is None:
                inst = self._meter.create_counter(name, description=name.replace("_", " "))
                self._counters[name] = inst
            inst.add(value, attributes=dict(tags))
        except Exception:
            return  # best-effort, non-throwing

    def histogram(self, name: str, tags: dict[str, str], value: float) -> None:
        try:
            inst = self._histograms.get(name)
            if inst is None:
                inst = self._meter.create_histogram(name, description=name.replace("_", " "))
                self._histograms[name] = inst
            inst.record(value, attributes=dict(tags))
        except Exception:
            return

    def gauge(self, name: str, tags: dict[str, str], value: float) -> None:
        try:
            if self._has_sync_gauge:
                inst = self._gauges.get(name)
                if inst is None:
                    inst = self._meter.create_gauge(name, description=name.replace("_", " "))
                    self._gauges[name] = inst
                inst.set(value, attributes=dict(tags))
            else:
                # ObservableGauge fallback: remember the last value per (name, tags)
                # and register a callback once that reads the store.
                key = (name, tuple(sorted(tags.items())))
                self._gauge_values[key] = (value, dict(tags))
                if name not in self._gauges:
                    from opentelemetry.metrics import Observation

                    def _callback(_options: Any, _name: str = name) -> list:
                        return [
                            Observation(val, attrs)
                            for (n, _), (val, attrs) in self._gauge_values.items()
                            if n == _name
                        ]

                    self._gauges[name] = self._meter.create_observable_gauge(
                        name, callbacks=[_callback], description=name.replace("_", " ")
                    )
        except Exception:
            return


def _require_otel() -> Any:
    """Return the opentelemetry metrics module, or raise MissingOptionalDependency."""
    try:
        from opentelemetry import metrics  # type: ignore
        import opentelemetry.sdk.metrics  # noqa: F401
    except ImportError as e:
        from activegraph.errors import MissingOptionalDependency

        raise MissingOptionalDependency(
            package="opentelemetry-sdk",
            feature="OpenTelemetryMetrics",
            extras="opentelemetry",
        ) from e
    return metrics
