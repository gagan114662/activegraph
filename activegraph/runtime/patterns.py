"""Cypher subset parser + matcher. CONTRACT v0.7 #8 / #9 / #11 / #12.

A strict subset of Cypher. Anything outside the subset raises
`UnsupportedPatternError` pointing at the offending token. A clean
subset is more useful than a fuzzy superset.

Supported (the LOCKED subset):
  * Node patterns:           (var:type {prop: value, ...})
  * Relationship patterns:   (a)-[var:rel_type]->(b)
                             (a)<-[var:rel_type]-(b)
  * Multi-hop:               (a)-[:r1]->(b)-[:r2]->(c)
  * WHERE clauses:           WHERE expr
      - comparisons:         a.confidence > 0.7
      - AND                  (NO OR — see CONTRACT v0.7 #8)
      - NOT                  NOT a.confidence > 0.5
      - NOT EXISTS { ... }   negation over a sub-pattern
  * Node `{prop: value}` is EQUALITY ONLY. Comparisons go in WHERE.
  * Identifiers:             ASCII letters/digits/underscore, leading letter.

Refused (will raise UnsupportedPatternError, pointing at the token):
  * RETURN — patterns don't return; bindings come out via ctx.matches
  * OPTIONAL MATCH
  * Variable-length paths -[*1..3]-
  * Aggregation (count, sum, ...)
  * WITH / pipeline composition
  * Subqueries beyond NOT EXISTS
  * OR in WHERE
  * UNION / UNWIND / CREATE / MERGE / SET / DELETE / DETACH

Parser produces a `Pattern` AST; the runtime calls
`Pattern.compile().matches(event, graph) -> list[Match]`. Compilation
happens once, at behavior registration (CONTRACT v0.7 #9).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional


class UnsupportedPatternError(SyntaxError):
    """Pattern uses syntax outside the v0.7 subset."""

    def __init__(self, message: str, *, at: Optional[str] = None) -> None:
        if at is not None:
            super().__init__(f"{message} (at: {at!r})")
        else:
            super().__init__(message)
        self.at = at


# ---------- AST -------------------------------------------------------------


@dataclass
class NodePat:
    var: Optional[str]
    type: Optional[str]
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class RelPat:
    var: Optional[str]
    type: str
    # 'right' = (a)-[]->(b); 'left' = (a)<-[]-(b). Undirected not supported.
    direction: str


@dataclass
class MatchClause:
    """Linear chain of nodes connected by relationships.

    `rels[i]` connects `nodes[i]` to `nodes[i+1]`. v0.7 patterns are
    always linear chains — branching is "register two patterns" (same
    spirit as "no OR in WHERE: register two behaviors").
    """

    nodes: list[NodePat]
    rels: list[RelPat]


@dataclass
class Comparison:
    """Either path-vs-literal or path-vs-path."""

    left_path: list[str]
    op: str
    right_path: Optional[list[str]] = None  # one of right_path / right_value
    right_value: Any = None


@dataclass
class NotExpr:
    inner: "BoolExpr"


@dataclass
class NotExists:
    sub_match: MatchClause


@dataclass
class AndExpr:
    parts: list["BoolExpr"] = field(default_factory=list)


BoolExpr = Any  # Union[Comparison, NotExpr, NotExists, AndExpr]


@dataclass
class Pattern:
    match: MatchClause
    where: Optional[BoolExpr]
    source: str  # original pattern string, for error messages and tracing

    def compile(self) -> "PatternMatcher":
        return PatternMatcher(self)


# ---------- Lexer -----------------------------------------------------------


_TOKEN_RE = re.compile(
    r"""
    \s+                      # whitespace (skipped)
  | (?P<STRING>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')
  | (?P<NUMBER>-?\d+\.\d+|-?\d+)
  # Arrows BEFORE OP so '<-' tokenizes as ARROW_L, not OP('<') + DASH.
  | (?P<ARROW_R>->)
  | (?P<ARROW_L><-)
  | (?P<OP><=|>=|<>|!=|=|<|>)
  | (?P<DASH>-)
  | (?P<STAR>\*)
  | (?P<LPAREN>\()
  | (?P<RPAREN>\))
  | (?P<LBRACK>\[)
  | (?P<RBRACK>\])
  | (?P<LBRACE>\{)
  | (?P<RBRACE>\})
  | (?P<COMMA>,)
  | (?P<COLON>:)
  | (?P<DOT>\.)
  | (?P<IDENT>[A-Za-z_][A-Za-z0-9_]*)
    """,
    re.VERBOSE,
)


# Tokens that the parser inspects by .kind. Keywords are recognized
# at parse time from IDENT (case-insensitive).
@dataclass(frozen=True)
class Tok:
    kind: str
    text: str
    pos: int


_KEYWORDS = {"WHERE", "AND", "OR", "NOT", "EXISTS", "TRUE", "FALSE", "NULL"}
_FORBIDDEN_KEYWORDS = {
    "RETURN", "OPTIONAL", "WITH", "MATCH", "UNWIND", "UNION", "CREATE",
    "MERGE", "SET", "DELETE", "DETACH", "REMOVE", "FOREACH", "CALL",
    "LIMIT", "SKIP", "ORDER",
}


def _tokenize(s: str) -> list[Tok]:
    out: list[Tok] = []
    pos = 0
    while pos < len(s):
        m = _TOKEN_RE.match(s, pos)
        if not m:
            raise UnsupportedPatternError(
                f"unexpected character at position {pos}", at=s[pos : pos + 8]
            )
        if m.lastgroup is None:
            pos = m.end()
            continue
        kind = m.lastgroup
        text = m.group(kind)
        if kind == "IDENT":
            upper = text.upper()
            if upper in _FORBIDDEN_KEYWORDS:
                raise UnsupportedPatternError(
                    f"keyword {upper!r} is not supported in the v0.7 Cypher subset "
                    f"(see CONTRACT v0.7 #8)",
                    at=text,
                )
            if upper in _KEYWORDS:
                kind = "KW_" + upper
                text = upper
        out.append(Tok(kind=kind, text=text, pos=pos))
        pos = m.end()
    out.append(Tok(kind="EOF", text="", pos=pos))
    return out


# ---------- Parser ----------------------------------------------------------


class _Parser:
    def __init__(self, tokens: list[Tok], source: str) -> None:
        self.tokens = tokens
        self.source = source
        self.i = 0

    def peek(self, offset: int = 0) -> Tok:
        return self.tokens[min(self.i + offset, len(self.tokens) - 1)]

    def eat(self, kind: str, text: Optional[str] = None) -> Tok:
        t = self.peek()
        if t.kind != kind or (text is not None and t.text != text):
            raise UnsupportedPatternError(
                f"expected {kind}"
                + (f" {text!r}" if text else "")
                + f", got {t.kind} {t.text!r}",
                at=t.text or self.source[t.pos : t.pos + 8],
            )
        self.i += 1
        return t

    def consume_if(self, kind: str, text: Optional[str] = None) -> Optional[Tok]:
        t = self.peek()
        if t.kind == kind and (text is None or t.text == text):
            self.i += 1
            return t
        return None

    # ---- top level ----

    def parse_pattern(self) -> Pattern:
        # Optional leading MATCH keyword is not in our grammar (forbidden
        # by lexer), so we just go straight into nodes/rels.
        match_clause = self.parse_match()
        where: Optional[BoolExpr] = None
        if self.consume_if("KW_WHERE"):
            where = self.parse_bool_expr()
        # Anything after WHERE (or after the match if no WHERE) is junk.
        if self.peek().kind != "EOF":
            t = self.peek()
            raise UnsupportedPatternError(
                f"unexpected trailing tokens after pattern: {t.kind} {t.text!r}",
                at=t.text,
            )
        return Pattern(match=match_clause, where=where, source=self.source)

    # ---- match (linear chain) ----

    def parse_match(self) -> MatchClause:
        first = self.parse_node()
        nodes: list[NodePat] = [first]
        rels: list[RelPat] = []
        while self.peek().kind in ("DASH", "ARROW_L"):
            rel = self.parse_rel()
            nxt = self.parse_node()
            rels.append(rel)
            nodes.append(nxt)
        return MatchClause(nodes=nodes, rels=rels)

    def parse_node(self) -> NodePat:
        self.eat("LPAREN")
        var: Optional[str] = None
        type_: Optional[str] = None
        if self.peek().kind == "IDENT":
            var = self.eat("IDENT").text
        if self.consume_if("COLON"):
            type_ = self.eat("IDENT").text
        props: dict[str, Any] = {}
        if self.consume_if("LBRACE"):
            props = self.parse_props()
            self.eat("RBRACE")
        self.eat("RPAREN")
        return NodePat(var=var, type=type_, properties=props)

    def parse_rel(self) -> RelPat:
        t = self.peek()
        if t.kind == "DASH":
            # -[...]-> or -[...]<- — the second is illegal (we don't
            # support undirected); the first is `direction=right`.
            self.eat("DASH")
            rel_var, rel_type = self._parse_edge_brackets()
            # Now expect ARROW_R (->); DASH (undirected -) is refused.
            arrow = self.peek()
            if arrow.kind == "ARROW_R":
                self.eat("ARROW_R")
                return RelPat(var=rel_var, type=rel_type, direction="right")
            if arrow.kind == "DASH":
                raise UnsupportedPatternError(
                    "undirected relationships are not supported; "
                    "use -[:type]-> or <-[:type]- (CONTRACT v0.7 #8)",
                    at="-",
                )
            raise UnsupportedPatternError(
                f"expected '->' after relationship, got {arrow.kind} {arrow.text!r}",
                at=arrow.text,
            )
        if t.kind == "ARROW_L":
            self.eat("ARROW_L")
            rel_var, rel_type = self._parse_edge_brackets()
            self.eat("DASH")
            return RelPat(var=rel_var, type=rel_type, direction="left")
        raise UnsupportedPatternError(
            f"expected relationship between nodes, got {t.kind} {t.text!r}",
            at=t.text,
        )

    def _parse_edge_brackets(self) -> tuple[Optional[str], str]:
        self.eat("LBRACK")
        # Reject variable-length path syntax explicitly so the error
        # message points at the right place.
        if self.consume_if("STAR") is not None:
            raise UnsupportedPatternError(
                "variable-length paths (-[*]-) are not supported (CONTRACT v0.7 #8)",
                at="*",
            )
        var: Optional[str] = None
        if self.peek().kind == "IDENT":
            var = self.eat("IDENT").text
        # Type is required: per the locked subset, relationships always
        # have an explicit type.
        if not self.consume_if("COLON"):
            t = self.peek()
            raise UnsupportedPatternError(
                "relationship type required (e.g. [:supports] or [r:supports])",
                at=t.text,
            )
        type_tok = self.eat("IDENT")
        self.eat("RBRACK")
        return var, type_tok.text

    def parse_props(self) -> dict[str, Any]:
        # `{key: literal, key: literal, ...}` — equality only.
        out: dict[str, Any] = {}
        if self.peek().kind == "RBRACE":
            return out
        while True:
            key = self.eat("IDENT").text
            self.eat("COLON")
            out[key] = self.parse_literal()
            if not self.consume_if("COMMA"):
                break
        return out

    # ---- where ----

    def parse_bool_expr(self) -> BoolExpr:
        parts: list[BoolExpr] = [self.parse_unary()]
        while self.consume_if("KW_AND"):
            parts.append(self.parse_unary())
        if self.consume_if("KW_OR"):
            raise UnsupportedPatternError(
                "OR is not supported in WHERE (CONTRACT v0.7 #8). "
                "Register two behaviors for either-or semantics.",
                at="OR",
            )
        if len(parts) == 1:
            return parts[0]
        return AndExpr(parts=parts)

    def parse_unary(self) -> BoolExpr:
        if self.consume_if("KW_NOT"):
            # NOT EXISTS { sub-pattern }
            if self.consume_if("KW_EXISTS"):
                self.eat("LBRACE")
                sub = self.parse_match()
                self.eat("RBRACE")
                return NotExists(sub_match=sub)
            return NotExpr(inner=self.parse_unary())
        if self.consume_if("LPAREN"):
            inner = self.parse_bool_expr()
            self.eat("RPAREN")
            return inner
        return self.parse_comparison()

    def parse_comparison(self) -> Comparison:
        left = self.parse_path()
        t = self.peek()
        if t.kind != "OP":
            raise UnsupportedPatternError(
                f"expected comparison operator, got {t.kind} {t.text!r}",
                at=t.text,
            )
        op = self.eat("OP").text
        # Right side: literal or another path
        nxt = self.peek()
        if nxt.kind in ("NUMBER", "STRING", "KW_TRUE", "KW_FALSE", "KW_NULL"):
            value = self.parse_literal()
            return Comparison(left_path=left, op=op, right_value=value)
        if nxt.kind == "IDENT":
            right_path = self.parse_path()
            return Comparison(left_path=left, op=op, right_path=right_path)
        raise UnsupportedPatternError(
            f"expected literal or path on rhs of comparison, got {nxt.kind} {nxt.text!r}",
            at=nxt.text,
        )

    def parse_path(self) -> list[str]:
        first = self.eat("IDENT").text
        parts = [first]
        while self.consume_if("DOT"):
            parts.append(self.eat("IDENT").text)
        return parts

    def parse_literal(self) -> Any:
        t = self.peek()
        if t.kind == "NUMBER":
            self.i += 1
            text = t.text
            return float(text) if ("." in text) else int(text)
        if t.kind == "STRING":
            self.i += 1
            # Strip surrounding quotes; minimal escape support.
            inner = t.text[1:-1]
            return inner.encode("utf-8").decode("unicode_escape")
        if t.kind == "KW_TRUE":
            self.i += 1
            return True
        if t.kind == "KW_FALSE":
            self.i += 1
            return False
        if t.kind == "KW_NULL":
            self.i += 1
            return None
        raise UnsupportedPatternError(
            f"expected literal, got {t.kind} {t.text!r}", at=t.text
        )


def parse(pattern: str) -> Pattern:
    """Public entry point. Raises UnsupportedPatternError on any
    parse failure with the offending token."""
    tokens = _tokenize(pattern)
    return _Parser(tokens, pattern).parse_pattern()


# ---------- Matcher ---------------------------------------------------------


@dataclass
class Match:
    """A single pattern binding.

    Maps variable names to object_ids (for nodes) or relation_ids (for
    rels). Variables for unbound nodes/rels (e.g. `(:claim)`, `[:supports]`)
    are absent. Handlers iterate `ctx.matches` to consume; the runtime
    fires the behavior once per event, not once per match
    (CONTRACT v0.7 #12).
    """

    bindings: dict[str, str]

    def __getitem__(self, key: str) -> str:
        return self.bindings[key]

    def get(self, key: str, default=None) -> Any:
        return self.bindings.get(key, default)


class PatternMatcher:
    """Pre-compiled matcher. Apply to (event, graph) → list[Match]."""

    def __init__(self, pattern: Pattern) -> None:
        self.pattern = pattern

    def matches(self, event, graph) -> list[Match]:
        # `event` is currently unused — patterns evaluate against the
        # post-event graph state. Future extensions may bind event
        # properties (e.g. `$event.payload.x`). v0.7 spec keeps it
        # graph-only.
        return list(self._enumerate_matches(self.pattern.match, graph))

    def _enumerate_matches(self, match_clause: MatchClause, graph):
        if not match_clause.nodes:
            return
        # Linear-chain match: enumerate bindings for nodes[0], then for
        # each subsequent node by following rels[i].
        candidates_0 = _candidate_objects(graph, match_clause.nodes[0])
        for obj0 in candidates_0:
            bindings: dict[str, str] = {}
            if match_clause.nodes[0].var:
                bindings[match_clause.nodes[0].var] = obj0.id
            yield from self._extend_chain(
                match_clause, graph, bindings, obj_chain=[obj0]
            )

    def _extend_chain(self, match_clause, graph, bindings, obj_chain):
        i = len(obj_chain) - 1
        # Done extending? Apply WHERE.
        if i == len(match_clause.rels):
            # Filter by WHERE.
            if self.pattern.where is None or _eval_where(
                self.pattern.where, bindings, graph
            ):
                yield Match(bindings=dict(bindings))
            return
        rel_pat = match_clause.rels[i]
        next_node_pat = match_clause.nodes[i + 1]
        src = obj_chain[-1]
        for rel, neighbor in _follow_relation(graph, src, rel_pat):
            if not _node_matches(neighbor, next_node_pat):
                continue
            # Forbid binding the same var to two different objects.
            new_bindings = dict(bindings)
            if rel_pat.var:
                if rel_pat.var in new_bindings and new_bindings[rel_pat.var] != rel.id:
                    continue
                new_bindings[rel_pat.var] = rel.id
            if next_node_pat.var:
                if (
                    next_node_pat.var in new_bindings
                    and new_bindings[next_node_pat.var] != neighbor.id
                ):
                    continue
                new_bindings[next_node_pat.var] = neighbor.id
            yield from self._extend_chain(
                match_clause, graph, new_bindings, obj_chain + [neighbor]
            )


def _candidate_objects(graph, node_pat: NodePat):
    """All objects that could fill `node_pat` ignoring relationships."""
    out = []
    for o in graph.all_objects():
        if _node_matches(o, node_pat):
            out.append(o)
    return out


def _node_matches(obj, node_pat: NodePat) -> bool:
    if node_pat.type is not None and obj.type != node_pat.type:
        return False
    for k, v in node_pat.properties.items():
        if obj.data.get(k) != v:
            return False
    return True


def _follow_relation(graph, src, rel_pat: RelPat) -> Iterator[tuple[Any, Any]]:
    """Yield (relation, neighbor_object) for every edge of the right type
    in the right direction leaving src.
    """
    for r in graph.all_relations():
        if r.type != rel_pat.type:
            continue
        if rel_pat.direction == "right":
            if r.source != src.id:
                continue
            neighbor = graph.get_object(r.target)
        else:  # 'left' — (src)<-[:r]-(neighbor) means r.target == src.id
            if r.target != src.id:
                continue
            neighbor = graph.get_object(r.source)
        if neighbor is None:
            continue
        yield r, neighbor


# ---------- WHERE evaluator -------------------------------------------------


_OPS = {
    "=": lambda a, b: a == b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "<>": lambda a, b: a != b,
    ">": lambda a, b: a is not None and b is not None and a > b,
    "<": lambda a, b: a is not None and b is not None and a < b,
    ">=": lambda a, b: a is not None and b is not None and a >= b,
    "<=": lambda a, b: a is not None and b is not None and a <= b,
}


def _eval_where(expr: BoolExpr, bindings: dict[str, str], graph) -> bool:
    if isinstance(expr, Comparison):
        left = _resolve_path(expr.left_path, bindings, graph)
        if expr.right_path is not None:
            right = _resolve_path(expr.right_path, bindings, graph)
        else:
            right = expr.right_value
        fn = _OPS.get(expr.op)
        if fn is None:
            raise UnsupportedPatternError(f"unknown operator {expr.op!r}")
        return fn(left, right)
    if isinstance(expr, NotExpr):
        return not _eval_where(expr.inner, bindings, graph)
    if isinstance(expr, AndExpr):
        return all(_eval_where(p, bindings, graph) for p in expr.parts)
    if isinstance(expr, NotExists):
        # NOT EXISTS { sub_match } — sub_match shares variable bindings
        # with the outer match: any variable used in both refers to the
        # same object id. If any binding of the sub_match exists that's
        # consistent with the outer bindings, NOT EXISTS is False.
        sub_matcher = PatternMatcher(
            Pattern(match=expr.sub_match, where=None, source="<sub>")
        )
        for m in sub_matcher.matches(event=None, graph=graph):
            # Outer bindings constrain sub-match bindings (shared vars).
            consistent = True
            for k, v in bindings.items():
                if k in m.bindings and m.bindings[k] != v:
                    consistent = False
                    break
            if consistent:
                return False
        return True
    raise UnsupportedPatternError(
        f"unrecognized where node {type(expr).__name__}"
    )


def _resolve_path(path: list[str], bindings: dict[str, str], graph) -> Any:
    """Resolve `a.confidence` etc. against bindings + graph."""
    if not path:
        return None
    head, *rest = path
    obj_id = bindings.get(head)
    if obj_id is None:
        # Could be a relation binding (NOT supported for property access
        # in v0.7 — relations have no .data attribute lookup syntax).
        return None
    obj = graph.get_object(obj_id)
    if obj is None:
        return None
    if not rest:
        # `a` alone → just return the object id; useful for equality.
        return obj.id
    # Walk: a.data.x.y or a.confidence (shorthand for a.data.confidence)
    cur: Any = obj.data
    # Allow `a.type` and `a.id` as direct attribute access.
    first = rest[0]
    if first in ("id", "type", "version"):
        cur = getattr(obj, first, None)
        rest = rest[1:]
    elif first == "data":
        cur = obj.data
        rest = rest[1:]
    # Anything else is treated as `a.<field>` → `a.data.<field>` (the
    # common case: `c.confidence` rather than `c.data.confidence`).
    for p in rest:
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return None
        if cur is None:
            return None
    return cur
