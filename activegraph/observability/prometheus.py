"""Prometheus implementation of the Metrics protocol. CONTRACT v0.8 #10.

Lazy import of ``prometheus_client`` so the dep stays optional. Install
with ``pip install 'activegraph[prometheus]'``.

The implementation creates Counter / Histogram / Gauge instruments
on-demand, keyed by ``(name, sorted-tag-keys)``. Tag values become
label values. We use the documented metric names as-is — they already
follow Prometheus conventions (``_total`` for counters, ``_seconds`` /
``_usd`` for histogram units, snake_case throughout).
"""

from __future__ import annotations

from typing import Any


class PrometheusMetrics:
    """Drop-in Metrics implementation backed by prometheus_client.

    Instruments are lazy. Tag keys for an instrument are fixed by the
    first observation. Per the Metrics protocol, all three methods are
    best-effort and non-throwing: prometheus_client errors (e.g. a
    re-registration collision when a name is observed with a different
    label-key set, or an invalid metric name) are contained, not
    propagated — matching NoOpMetrics and OpenTelemetryMetrics. The
    standard metric list's fixed tag schemas mean these collisions do
    not arise in normal use; the containment is for ad-hoc / off-contract
    callers, who must never see an exception escape a metrics call.
    """

    def __init__(self, registry: Any | None = None) -> None:
        client = _require_client()
        self._client = client
        self._registry = registry if registry is not None else client.REGISTRY
        self._counters: dict[tuple, Any] = {}
        self._histograms: dict[tuple, Any] = {}
        self._gauges: dict[tuple, Any] = {}

    @staticmethod
    def available() -> bool:
        try:
            import prometheus_client  # noqa: F401
        except ImportError:
            return False
        return True

    # ---- protocol ----

    def counter(self, name: str, tags: dict[str, str], value: float = 1.0) -> None:
        try:
            keys = tuple(sorted(tags.keys()))
            key = (name, keys)
            c = self._counters.get(key)
            if c is None:
                c = self._client.Counter(
                    name, name.replace("_", " "), labelnames=keys,
                    registry=self._registry,
                )
                self._counters[key] = c
            if keys:
                c.labels(**tags).inc(value)
            else:
                c.inc(value)
        except Exception:
            return  # best-effort, non-throwing (Metrics protocol contract)

    def histogram(self, name: str, tags: dict[str, str], value: float) -> None:
        try:
            keys = tuple(sorted(tags.keys()))
            key = (name, keys)
            h = self._histograms.get(key)
            if h is None:
                h = self._client.Histogram(
                    name, name.replace("_", " "), labelnames=keys,
                    registry=self._registry,
                )
                self._histograms[key] = h
            if keys:
                h.labels(**tags).observe(value)
            else:
                h.observe(value)
        except Exception:
            return  # best-effort, non-throwing (Metrics protocol contract)

    def gauge(self, name: str, tags: dict[str, str], value: float) -> None:
        try:
            keys = tuple(sorted(tags.keys()))
            key = (name, keys)
            g = self._gauges.get(key)
            if g is None:
                g = self._client.Gauge(
                    name, name.replace("_", " "), labelnames=keys,
                    registry=self._registry,
                )
                self._gauges[key] = g
            if keys:
                g.labels(**tags).set(value)
            else:
                g.set(value)
        except Exception:
            return  # best-effort, non-throwing (Metrics protocol contract)


def _require_client() -> Any:
    try:
        import prometheus_client  # type: ignore
    except ImportError as e:
        from activegraph.errors import MissingOptionalDependency
        raise MissingOptionalDependency(
            package="prometheus_client",
            feature="PrometheusMetrics",
            extras="prometheus",
        ) from e
    return prometheus_client
