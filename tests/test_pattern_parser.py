"""Cypher subset parser tests. CONTRACT v0.7 #8.

Every supported construct + every explicitly-refused construct.
Tests are short and exhaustive — a parser regression should fall out
of one of these.
"""

from __future__ import annotations

import pytest

from activegraph.runtime.patterns import (
    AndExpr,
    Comparison,
    NotExists,
    NotExpr,
    Pattern,
    UnsupportedPatternError,
    parse,
)


# ---------- happy path: every supported construct --------------------------


def test_single_node_no_type():
    p = parse("(a)")
    assert isinstance(p, Pattern)
    assert len(p.match.nodes) == 1
    assert p.match.nodes[0].var == "a"
    assert p.match.nodes[0].type is None
    assert p.where is None


def test_node_with_type():
    p = parse("(a:claim)")
    assert p.match.nodes[0].type == "claim"


def test_node_with_properties():
    p = parse("(a:claim {confidence: 0.9, status: \"open\"})")
    assert p.match.nodes[0].properties == {"confidence": 0.9, "status": "open"}


def test_anonymous_node():
    p = parse("(:claim)")
    assert p.match.nodes[0].var is None
    assert p.match.nodes[0].type == "claim"


def test_directed_right_rel():
    p = parse("(a)-[:supports]->(b)")
    assert len(p.match.rels) == 1
    assert p.match.rels[0].type == "supports"
    assert p.match.rels[0].direction == "right"
    assert p.match.rels[0].var is None


def test_directed_left_rel():
    p = parse("(a)<-[:supports]-(b)")
    assert p.match.rels[0].direction == "left"


def test_relationship_variable_binding():
    """CONTRACT v0.7 #8: -[r:type]-> binds the relation to r."""
    p = parse("(a)-[r:supports]->(b)")
    assert p.match.rels[0].var == "r"


def test_multi_hop():
    p = parse("(a:claim)-[:supports]->(b:doc)-[:cites]->(c:source)")
    assert len(p.match.nodes) == 3
    assert len(p.match.rels) == 2
    assert [n.type for n in p.match.nodes] == ["claim", "doc", "source"]
    assert [r.type for r in p.match.rels] == ["supports", "cites"]


def test_where_simple_comparison():
    p = parse("(a:claim) WHERE a.confidence > 0.7")
    assert isinstance(p.where, Comparison)
    assert p.where.op == ">"
    assert p.where.right_value == 0.7


def test_where_and():
    p = parse("(a:claim) WHERE a.confidence > 0.7 AND a.status = \"open\"")
    assert isinstance(p.where, AndExpr)
    assert len(p.where.parts) == 2


def test_where_not():
    p = parse("(a:claim) WHERE NOT a.confidence < 0.3")
    assert isinstance(p.where, NotExpr)


def test_where_not_exists():
    p = parse(
        "(a:claim) WHERE NOT EXISTS { (a)-[:supersedes]->(b:claim) }"
    )
    assert isinstance(p.where, NotExists)
    assert p.where.sub_match.nodes[0].var == "a"
    assert p.where.sub_match.rels[0].type == "supersedes"


def test_where_path_vs_path():
    p = parse("(a:c)-[:r]->(b:c) WHERE a.confidence > b.confidence")
    assert isinstance(p.where, Comparison)
    assert p.where.right_path == ["b", "confidence"]


def test_property_path_a_data_field():
    p = parse("(a:claim) WHERE a.data.priority = 3")
    assert isinstance(p.where, Comparison)
    assert p.where.left_path == ["a", "data", "priority"]


def test_all_comparison_operators_parse():
    for op in ("=", "<", ">", "<=", ">=", "!=", "<>"):
        p = parse(f"(a:c) WHERE a.x {op} 1")
        assert isinstance(p.where, Comparison)
        assert p.where.op == op


def test_string_literal_double_quotes():
    p = parse('(a:c) WHERE a.x = "hello"')
    assert p.where.right_value == "hello"


def test_string_literal_single_quotes():
    p = parse("(a:c) WHERE a.x = 'hello'")
    assert p.where.right_value == "hello"


def test_boolean_literals():
    p = parse("(a:c) WHERE a.x = TRUE")
    assert p.where.right_value is True
    p = parse("(a:c) WHERE a.x = FALSE")
    assert p.where.right_value is False


def test_null_literal():
    p = parse("(a:c) WHERE a.x = NULL")
    assert p.where.right_value is None


# ---------- failure cases: anything OUTSIDE the subset ---------------------


def test_or_in_where_rejected():
    """CONTRACT v0.7 #8: no OR in WHERE for v0.7."""
    with pytest.raises(UnsupportedPatternError, match="OR is not supported"):
        parse("(a:c) WHERE a.x > 0 OR a.x < -1")


def test_return_rejected():
    """CONTRACT v0.7 #8: patterns produce bindings via ctx.matches; no RETURN."""
    with pytest.raises(UnsupportedPatternError, match="RETURN"):
        parse("(a:c) RETURN a")


def test_optional_match_rejected():
    with pytest.raises(UnsupportedPatternError, match="OPTIONAL"):
        parse("OPTIONAL (a:c)")


def test_with_clause_rejected():
    with pytest.raises(UnsupportedPatternError, match="WITH"):
        parse("(a:c) WITH a")


def test_match_keyword_rejected_too():
    """We don't write `MATCH (a:c)` either — the pattern starts directly."""
    with pytest.raises(UnsupportedPatternError, match="MATCH"):
        parse("MATCH (a:c)")


def test_variable_length_path_rejected():
    """CONTRACT v0.7 #8: variable-length paths come in a later release."""
    with pytest.raises(UnsupportedPatternError, match="variable-length"):
        parse("(a:c)-[*]->(b:c)")


def test_undirected_relationship_rejected():
    with pytest.raises(UnsupportedPatternError, match="undirected"):
        parse("(a:c)-[:r]-(b:c)")


def test_relationship_without_type_rejected():
    with pytest.raises(UnsupportedPatternError, match="type required"):
        parse("(a)-[]->(b)")


def test_create_rejected():
    with pytest.raises(UnsupportedPatternError, match="CREATE"):
        parse("CREATE (a:c)")


def test_merge_rejected():
    with pytest.raises(UnsupportedPatternError, match="MERGE"):
        parse("MERGE (a:c)")


def test_node_property_must_be_literal():
    """{prop: value} accepts only literals; comparisons go in WHERE."""
    with pytest.raises(UnsupportedPatternError):
        parse("(a:c {x: y})")


def test_trailing_junk_rejected():
    with pytest.raises(UnsupportedPatternError, match="trailing"):
        parse("(a:c) junk_here")


def test_unmatched_paren_rejected():
    with pytest.raises(UnsupportedPatternError):
        parse("(a:c")


def test_unsupported_character_rejected():
    with pytest.raises(UnsupportedPatternError, match="unexpected character"):
        parse("(a:c) WHERE a.x ?? 1")
