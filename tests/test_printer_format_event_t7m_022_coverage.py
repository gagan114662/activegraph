"""T7 medium repetition run 022 — coverage for ``format_event``.

Target: ``activegraph.trace.printer.format_event`` — previously exercised by no
test file (``pytest --collect-only -k format_event`` collected 0 tests).

``format_event`` is the single dispatch seam of the trace printer: it maps an
``Event`` to a one-line human-readable rendering. Known event types route to a
dedicated formatter via the ``_FORMATTERS`` table; ``llm.requested`` is special
cased so the ``hide_prompt_normalized`` keyword can be threaded through; any
unknown type falls back to ``_fmt_event_emitted``. These tests exercise the real
``Event`` dataclass and the real ``format_event`` function — nothing about the
API under test is mocked.

The test function names embed ``activegraph_trace_printer_format_event`` so that
``pytest --collect-only -k`` matching either the dotted fully-qualified name or
the underscored symbol form selects them.
"""

from __future__ import annotations

from activegraph.core.event import Event
from activegraph.trace.printer import format_event


def test_activegraph_trace_printer_format_event_known_type_routes_to_formatter() -> None:
    """Happy path: a known event type uses its dedicated formatter."""
    event = Event(
        id="evt_001",
        type="goal.created",
        payload={"goal": "ship the feature"},
        actor="maya",
    )

    rendered = format_event(event)

    # _fmt_goal_created renders: [goal.created]<actor>: "<goal>"
    assert "goal.created" in rendered
    assert "maya" in rendered
    assert '"ship the feature"' in rendered


def test_activegraph_trace_printer_format_event_unknown_type_falls_back_to_event_emitted() -> None:
    """Boundary: an unknown/custom event type falls back to _fmt_event_emitted.

    The fallback renders the raw type plus its payload key=value pairs under the
    ``event.emitted`` tag rather than raising.
    """
    event = Event(
        id="evt_custom",
        type="claim.extracted",
        payload={"confidence": 0.9, "label": "high"},
    )

    rendered = format_event(event)

    # Fallback tag is event.emitted, body leads with the real type.
    assert "event.emitted" in rendered
    assert "claim.extracted" in rendered
    assert "confidence=0.9" in rendered
    assert "label=high" in rendered


def test_activegraph_trace_printer_format_event_llm_requested_honors_hide_prompt_normalized() -> None:
    """Distinct configuration: llm.requested threads hide_prompt_normalized.

    The ``prompt_normalized=true`` segment is emitted by default but suppressed
    when ``hide_prompt_normalized=True`` is passed — proving the kwarg actually
    reaches the special-cased formatter.
    """
    event = Event(
        id="evt_llm",
        type="llm.requested",
        payload={
            "behavior": "extract_claims",
            "model": "claude-opus-4-8",
            "prompt_normalized": True,
        },
    )

    shown = format_event(event)
    hidden = format_event(event, hide_prompt_normalized=True)

    assert "llm.requested" in shown
    assert "model=claude-opus-4-8" in shown
    assert "prompt_normalized=true" in shown
    # The kwarg suppresses the rollup-able per-line flag.
    assert "prompt_normalized=true" not in hidden
    assert "model=claude-opus-4-8" in hidden
