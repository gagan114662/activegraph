"""T7 medium 017 coverage for ``ActiveGraphError.is_structured``.

``is_structured()`` is the gateway that decides whether an error renders in
the locked v1.0 structured format or falls back to the legacy single-message
form. It returns True only when ALL THREE structured fields
(``what_failed``, ``why``, ``how_to_fix``) are populated. These tests exercise
the real error type (no mocks of the API under test) across the structured
happy path and the boundary cases where exactly one field is missing.
"""

from __future__ import annotations

from activegraph.errors import ActiveGraphError, ConfigurationError


def test_is_structured_true_when_all_three_fields_present() -> None:
    """Happy path: a fully structured error reports is_structured() True and
    renders the locked format (so __str__ contains the section headers)."""
    err = ConfigurationError(
        "budget is invalid",
        what_failed="The configured budget was rejected",
        why="A negative cost ceiling is not a valid budget",
        how_to_fix="Pass a non-negative cost limit",
    )
    assert err.is_structured() is True
    rendered = str(err)
    assert "What failed:" in rendered
    assert "Why:" in rendered
    assert "How to fix:" in rendered


def test_is_structured_false_for_legacy_single_message() -> None:
    """Legacy boundary: an error built from a bare positional message (no
    structured fields) reports is_structured() False and renders verbatim."""
    err = ConfigurationError("something went wrong")
    assert err.is_structured() is False
    assert str(err) == "something went wrong"


def test_is_structured_false_when_what_failed_missing() -> None:
    """Boundary: is_structured() requires ALL THREE fields. Dropping
    what_failed (empty string) flips the result to False — proving AND
    semantics rather than an OR/any-field-present shortcut."""
    err = ActiveGraphError(
        "partial structured error",
        what_failed="",
        why="reason",
        how_to_fix="fix",
    )
    assert err.is_structured() is False
    assert str(err) == "partial structured error"
    assert "What failed:" not in str(err)


def test_is_structured_false_when_why_missing() -> None:
    """Boundary: dropping ``why`` alone must still yield False."""
    err = ActiveGraphError(
        "partial structured error",
        what_failed="failed",
        why="",
        how_to_fix="fix",
    )
    assert err.is_structured() is False
    assert str(err) == "partial structured error"


def test_is_structured_false_when_how_to_fix_missing() -> None:
    """Boundary: dropping ``how_to_fix`` alone must still yield False."""
    err = ActiveGraphError(
        "partial structured error",
        what_failed="failed",
        why="reason",
        how_to_fix="",
    )
    assert err.is_structured() is False
    assert str(err) == "partial structured error"
