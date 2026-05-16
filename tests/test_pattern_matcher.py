"""Cypher subset matcher tests. CONTRACT v0.7 #9 / #12.

Exercises every kind of match: nodes, relationships, multi-hop,
WHERE, NOT EXISTS, property predicates. Uses a bare Graph instead
of going through the full Runtime — the matcher is pure over
(event, graph) and these tests keep that surface narrow.
"""

from __future__ import annotations

from activegraph import Graph
from activegraph.runtime.patterns import parse


def _build_graph_with_two_claims_one_contradicts() -> Graph:
    g = Graph()
    a = g.add_object("claim", {"text": "A", "confidence": 0.9, "status": "open"})
    b = g.add_object("claim", {"text": "B", "confidence": 0.8, "status": "open"})
    c = g.add_object("claim", {"text": "C", "confidence": 0.3, "status": "open"})
    g.add_relation(a.id, b.id, "contradicts")
    g.add_relation(a.id, c.id, "supports")
    return g


def test_match_single_node_by_type():
    g = _build_graph_with_two_claims_one_contradicts()
    matcher = parse("(c:claim)").compile()
    matches = matcher.matches(event=None, graph=g)
    assert len(matches) == 3
    # bindings carry the var name
    assert all("c" in m.bindings for m in matches)


def test_match_node_property_equality():
    g = _build_graph_with_two_claims_one_contradicts()
    matcher = parse("(c:claim {confidence: 0.9})").compile()
    matches = matcher.matches(event=None, graph=g)
    assert len(matches) == 1


def test_match_relationship_by_type():
    g = _build_graph_with_two_claims_one_contradicts()
    matcher = parse("(a:claim)-[:contradicts]->(b:claim)").compile()
    matches = matcher.matches(event=None, graph=g)
    assert len(matches) == 1
    assert matches[0]["a"] != matches[0]["b"]


def test_match_relationship_bind_relation_var():
    g = _build_graph_with_two_claims_one_contradicts()
    matcher = parse("(a:claim)-[r:contradicts]->(b:claim)").compile()
    matches = matcher.matches(event=None, graph=g)
    assert len(matches) == 1
    assert "r" in matches[0].bindings
    assert matches[0]["r"].startswith("rel_")


def test_match_relationship_directed_left():
    g = _build_graph_with_two_claims_one_contradicts()
    # (b)<-[:contradicts]-(a) is the same edge from the other side.
    matcher = parse("(b:claim)<-[:contradicts]-(a:claim)").compile()
    matches = matcher.matches(event=None, graph=g)
    assert len(matches) == 1


def test_match_no_relationship_no_match():
    g = _build_graph_with_two_claims_one_contradicts()
    matcher = parse("(a:claim)-[:cites]->(b:claim)").compile()
    assert matcher.matches(event=None, graph=g) == []


def test_match_multi_hop():
    g = Graph()
    a = g.add_object("claim", {})
    b = g.add_object("source", {})
    c = g.add_object("doc", {})
    g.add_relation(a.id, b.id, "cites")
    g.add_relation(b.id, c.id, "in")
    matcher = parse("(a:claim)-[:cites]->(b:source)-[:in]->(c:doc)").compile()
    matches = matcher.matches(event=None, graph=g)
    assert len(matches) == 1
    assert matches[0]["a"] == a.id
    assert matches[0]["b"] == b.id
    assert matches[0]["c"] == c.id


def test_where_filters_matches():
    g = _build_graph_with_two_claims_one_contradicts()
    matcher = parse(
        "(c:claim) WHERE c.confidence > 0.5"
    ).compile()
    matches = matcher.matches(event=None, graph=g)
    assert len(matches) == 2  # A (0.9) + B (0.8); C (0.3) excluded


def test_where_and_filters_matches():
    g = _build_graph_with_two_claims_one_contradicts()
    matcher = parse(
        "(c:claim) WHERE c.confidence > 0.7 AND c.status = \"open\""
    ).compile()
    matches = matcher.matches(event=None, graph=g)
    assert len(matches) == 2


def test_where_not_inverts():
    g = _build_graph_with_two_claims_one_contradicts()
    matcher = parse("(c:claim) WHERE NOT c.confidence > 0.5").compile()
    matches = matcher.matches(event=None, graph=g)
    assert len(matches) == 1  # only C (0.3)


def test_where_not_exists_excludes_matched_subpatterns():
    # Claim A is contradicted by another claim; claim B is not.
    g = Graph()
    a = g.add_object("claim", {"text": "A"})
    b = g.add_object("claim", {"text": "B"})
    contradictor = g.add_object("claim", {"text": "X"})
    g.add_relation(contradictor.id, a.id, "contradicts")
    matcher = parse(
        "(c:claim) WHERE NOT EXISTS { (x:claim)-[:contradicts]->(c) }"
    ).compile()
    matches = matcher.matches(event=None, graph=g)
    # B and X have no incoming contradicts; A has one → excluded.
    ids = sorted(m["c"] for m in matches)
    assert ids == sorted([b.id, contradictor.id])


def test_pattern_with_two_high_confidence_claims_and_contradiction():
    """The killer demo's critic pattern."""
    g = _build_graph_with_two_claims_one_contradicts()
    matcher = parse(
        "(c1:claim)-[r:contradicts]->(c2:claim) "
        "WHERE c1.confidence > 0.7 AND c2.confidence > 0.7"
    ).compile()
    matches = matcher.matches(event=None, graph=g)
    assert len(matches) == 1


def test_no_matches_returns_empty_list():
    g = Graph()
    g.add_object("claim", {"confidence": 0.1})
    matcher = parse("(c:claim) WHERE c.confidence > 0.99").compile()
    assert matcher.matches(event=None, graph=g) == []


def test_var_path_resolves_to_object_id():
    """`a` (no field) resolves to the object's id — useful for equality."""
    g = _build_graph_with_two_claims_one_contradicts()
    a = g.all_objects()[0]
    matcher = parse(f'(c:claim) WHERE c = "{a.id}"').compile()
    matches = matcher.matches(event=None, graph=g)
    assert len(matches) == 1
    assert matches[0]["c"] == a.id


def test_object_field_access_via_a_type():
    g = _build_graph_with_two_claims_one_contradicts()
    matcher = parse('(c) WHERE c.type = "claim"').compile()
    matches = matcher.matches(event=None, graph=g)
    assert len(matches) == 3
