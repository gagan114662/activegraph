"""T7 medium 023 coverage — UnsupportedPatternError.refused_feature.

Covers the canonical factory classmethod that constructs the
"recognized-but-refused Cypher feature" error for the v0.7 pattern
subset. The symbol collected 0 tests before this file. Real fixtures
(the actual exception class), no mocks of the API under test.
"""

from __future__ import annotations

import pytest

from activegraph.errors import ActiveGraphError, PatternError
from activegraph.runtime.patterns import UnsupportedPatternError


def test_refused_feature_happy_path_uses_default_why_and_embeds_feature() -> None:
    """Happy path: feature + workaround only. The feature string is
    embedded verbatim in the summary (operators grep for it), the default
    `why` references the locked subset, and the structured-error surface
    is fully populated."""
    err = UnsupportedPatternError.refused_feature(
        feature="OPTIONAL MATCH",
        workaround="Register a second behavior for the optional sub-pattern.",
    )

    # Type lineage: refused_feature returns the structured error that is
    # both a PatternError and the framework's ActiveGraphError, and stays
    # catchable as a plain SyntaxError for legacy user code.
    assert isinstance(err, UnsupportedPatternError)
    assert isinstance(err, PatternError)
    assert isinstance(err, ActiveGraphError)
    assert isinstance(err, SyntaxError)

    # Feature embedded verbatim in the rendered message + what_failed.
    rendered = str(err)
    assert "OPTIONAL MATCH is not supported in the v0.7 Cypher subset" in rendered
    assert "OPTIONAL MATCH" in err.what_failed

    # Default why mentions the locked subset / contract.
    assert "v0.7 #8" in err.why
    assert "audit trail" in err.why

    # how_to_fix is exactly the supplied workaround.
    assert err.how_to_fix == "Register a second behavior for the optional sub-pattern."

    # Fully structured (all three fields non-empty) and no `at` was given.
    assert err.is_structured() is True
    assert err.at is None
    assert "at" not in err.context


def test_refused_feature_boundary_custom_why_and_at_location() -> None:
    """Boundary/alternate config: explicit `why` override and an `at`
    location. The override replaces the default prose entirely, and `at`
    flows onto the instance and into the structured context dict."""
    err = UnsupportedPatternError.refused_feature(
        feature="variable-length path",
        workaround="Express the hops as explicit relationship patterns.",
        at="(a)-[*1..3]->(b)",
        why="Unbounded path length cannot be exhaustively tested.",
    )

    # Custom why fully replaces the default — the default prose is absent.
    assert err.why == "Unbounded path length cannot be exhaustively tested."
    assert "exhaustively testable" not in err.why

    # `at` is captured on the instance and inside the structured context.
    assert err.at == "(a)-[*1..3]->(b)"
    assert err.context.get("at") == "(a)-[*1..3]->(b)"

    # Feature + workaround still wired through correctly.
    assert "variable-length path" in str(err)
    assert "variable-length path" in err.what_failed
    assert err.how_to_fix == "Express the hops as explicit relationship patterns."

    # Still a valid structured error and a real raisable exception.
    assert err.is_structured() is True
    with pytest.raises(UnsupportedPatternError):
        raise err
