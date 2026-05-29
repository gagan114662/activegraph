"""T7 repeat-hard 011 — docstring↔code drift for the pattern identifier rule.

The `activegraph.runtime.patterns` module docstring documents the LOCKED Cypher
subset, and line 19 of that docstring states:

    * Identifiers:             ASCII letters/digits/underscore, leading letter.

i.e. an identifier may contain letters/digits/underscores but MUST begin with a
letter. The lexer's `IDENT` regex, however, is ``[A-Za-z_][A-Za-z0-9_]*`` — which
also accepts a *leading underscore*. So a pattern like ``(_x:claim)`` parses
cleanly even though the documented subset says it should be refused as a syntax
error pointing at the offending token.

These tests assert the DOCUMENTED behavior: a leading-underscore identifier (in a
node variable, a node type, a relationship variable, a relationship type, or a
WHERE binding path) is outside the locked subset and must raise
``UnsupportedPatternError``. They FAIL against the current code (which silently
accepts the leading underscore) and PASS once the lexer enforces the leading-letter
rule the docstring promises.
"""

from __future__ import annotations

import pytest

from activegraph.runtime.patterns import UnsupportedPatternError, parse


def test_leading_underscore_node_var_is_refused() -> None:
    # Documented: identifiers must have a leading letter. `_x` does not.
    with pytest.raises(UnsupportedPatternError):
        parse("(_x:claim)")


def test_leading_underscore_node_type_is_refused() -> None:
    with pytest.raises(UnsupportedPatternError):
        parse("(c:_claim)")


def test_leading_underscore_rel_type_is_refused() -> None:
    with pytest.raises(UnsupportedPatternError):
        parse("(a:claim)-[:_supports]->(b:claim)")


def test_leading_underscore_where_path_is_refused() -> None:
    with pytest.raises(UnsupportedPatternError):
        parse("(c:claim) WHERE _c.confidence > 0.5")


def test_leading_letter_identifier_still_parses() -> None:
    # The fix must NOT break legitimate leading-letter identifiers (which may
    # still contain underscores after the first character).
    p = parse("(my_var:claim_type)")
    assert p.match.nodes[0].var == "my_var"
    assert p.match.nodes[0].type == "claim_type"
