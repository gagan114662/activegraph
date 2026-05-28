"""T7 medium repetition run 001 — coverage for
``activegraph.observability.logging.redact_payload`` and its companion
``set_payload_redactor``.

These exercise the real module-level redactor hook (no mocking of the API
under test). A fixture saves and restores the global redactor state so the
tests do not leak configuration into the rest of the suite.
"""

from __future__ import annotations

import pytest

from activegraph.observability.logging import (
    redact_payload,
    set_payload_redactor,
)


@pytest.fixture(autouse=True)
def _restore_redactor():
    """Save the installed redactor, run the test, then restore it.

    Guarantees the global hook is left exactly as found regardless of how
    the test mutates it — keeps the rest of the suite deterministic.
    """
    from activegraph.observability import logging as _log_mod

    saved = _log_mod._payload_redactor_state["fn"]
    try:
        yield
    finally:
        _log_mod._payload_redactor_state["fn"] = saved


def test_redact_payload_identity_when_no_redactor_installed():
    """Happy path: with no redactor configured, the payload passes through
    unchanged (identity)."""
    set_payload_redactor(None)
    payload = {"user": "alice", "token": "secret"}

    out = redact_payload(payload)

    assert out == {"user": "alice", "token": "secret"}
    # Identity means the same object is returned, not a copy.
    assert out is payload


def test_redact_payload_applies_installed_redactor():
    """Configured path: an installed redactor transforms the payload before
    it would enter a log record."""

    def _scrub(p: dict) -> dict:
        return {k: ("***" if k == "token" else v) for k, v in p.items()}

    set_payload_redactor(_scrub)

    out = redact_payload({"user": "alice", "token": "secret"})

    assert out == {"user": "alice", "token": "***"}


def test_redact_payload_reverts_to_identity_after_redactor_removed():
    """Boundary/removal: installing then clearing (None) the redactor returns
    to identity behavior — set_payload_redactor is documented as idempotent
    and reversible."""

    def _drop_all(_p: dict) -> dict:
        return {}

    set_payload_redactor(_drop_all)
    assert redact_payload({"a": 1}) == {}

    # Remove the redactor — behavior must revert to identity.
    set_payload_redactor(None)
    restored = {"a": 1, "b": 2}
    assert redact_payload(restored) == {"a": 1, "b": 2}


def test_redact_payload_empty_payload_is_handled():
    """Edge: an empty payload with no redactor returns an empty dict, not an
    error."""
    set_payload_redactor(None)

    assert redact_payload({}) == {}
