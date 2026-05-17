"""v1.0 PR-A: ActiveGraphError format + ReplayError reference category.

CONTRACT v1.0 #3 locks the error message format. This file is the canary
for any drift in that format AND the snapshot baseline for every error
class as it migrates into the hierarchy. Each PR in the v1.0 error
series (PR-B through PR-F) adds new snapshot tests here; the harness
below is the same for every error class.

If the format changes intentionally, run with ``UPDATE_SNAPSHOTS=1`` and
update the doc-site reference page at ``docs/reference/errors/<slug>.md``
in the same commit.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from activegraph import (
    ActiveGraphError,
    ApprovalNotFoundError,
    ConfigurationError,
    CorruptedEventPayloadError,
    DuplicateEventError,
    EventNotFoundError,
    ExecutionError,
    InvalidStoreURL,
    LLMBehaviorError,
    NonSerializableEventError,
    PackError,
    PatternError,
    RegistrationError,
    ReplayDivergenceError,
    ReplayError,
    SchemaVersionMismatch,
    StorageError,
    ToolError,
    UnknownToolError,
    UnsupportedPatternError,
)


SNAPSHOTS_DIR = Path(__file__).parent / "snapshots" / "errors"


# ---------- harness ------------------------------------------------------


def _check_snapshot(name: str, err: Exception) -> None:
    """Compare ``str(err)`` against ``tests/snapshots/errors/<name>.txt``.

    Run with ``UPDATE_SNAPSHOTS=1`` to write the snapshot. Snapshots are
    byte-identical; trailing newline is part of the file so editors that
    auto-add one don't drift the diff.
    """
    path = SNAPSHOTS_DIR / f"{name}.txt"
    actual = str(err) + "\n"
    if os.environ.get("UPDATE_SNAPSHOTS"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual)
    assert path.exists(), (
        f"missing snapshot {path}. Run with UPDATE_SNAPSHOTS=1 to create it."
    )
    expected = path.read_text()
    assert actual == expected, (
        f"{name} drifted from snapshot. If intentional, run with "
        f"UPDATE_SNAPSHOTS=1 and update docs/reference/errors/ in the same "
        f"commit."
    )


# ---------- format invariants -------------------------------------------


_SECTIONS = ("What failed:", "Why:", "How to fix:", "More:")


def _make_dummy(cls: type[ActiveGraphError]) -> ActiveGraphError:
    return cls(
        "summary line for the snapshot",
        what_failed="the specific thing that broke (with a name)",
        why="the root cause, in one sentence",
        how_to_fix="run the canonical fix command",
    )


def _assert_format_compliant(err: Exception) -> None:
    """Verify a rendered error matches CONTRACT v1.0 #3 structurally.

    Structural rather than regex — the body of each section is allowed to
    span multiple lines with internal blank-line paragraph breaks, which
    a strict regex would reject. The check verifies: title line shape,
    every required section header appears in order, every section body
    is at least one indented line, ``More:`` body is a doc URL.
    """
    msg = str(err)
    first, _, rest = msg.partition("\n")
    assert ": " in first, f"missing title-line colon: {first!r}"
    class_name, _, summary = first.partition(": ")
    assert class_name == type(err).__name__, (
        f"title class {class_name!r} != {type(err).__name__!r}"
    )
    assert summary, "summary is empty"

    positions = [msg.find(f"\n{h}\n") for h in _SECTIONS]
    for header, pos in zip(_SECTIONS, positions):
        assert pos != -1, f"missing section {header!r}"
    assert positions == sorted(positions), (
        f"sections out of order: {list(zip(_SECTIONS, positions))}"
    )

    # Every section body has at least one continuation line at 2-space
    # indent (the format's lock-in column).
    for header in _SECTIONS[:-1]:
        body = msg.split(f"\n{header}\n", 1)[1].split("\n\n", 1)[0]
        assert body.startswith("  "), (
            f"section {header!r} body does not start with 2-space indent:\n{body!r}"
        )

    more_body = msg.split("\nMore:\n  ", 1)[1].strip()
    assert more_body.startswith("https://"), (
        f"More: body is not a URL: {more_body!r}"
    )


@pytest.mark.parametrize(
    "cls",
    [
        ConfigurationError,
        RegistrationError,
        ExecutionError,
        ReplayError,
        StorageError,
        PatternError,
        PackError,
    ],
)
def test_every_category_base_obeys_format(cls: type[ActiveGraphError]) -> None:
    """CONTRACT v1.0 #3 — every category base produces a message that
    matches the locked format. Structural check, multi-line bodies
    allowed."""
    _assert_format_compliant(_make_dummy(cls))


def test_every_category_base_exposes_structured_fields() -> None:
    """The four structured fields plus ``.context`` and ``.doc_url`` are
    the programmatic API. Tools (the doc-site error catalog, the
    machine-readable failure log) read these directly instead of
    parsing ``str(err)``."""
    err = _make_dummy(ConfigurationError)
    assert err.what_failed == "the specific thing that broke (with a name)"
    assert err.why == "the root cause, in one sentence"
    assert err.how_to_fix == "run the canonical fix command"
    assert err.context == {}
    assert err.doc_url.startswith("https://")
    assert err.doc_url.endswith("/errors/configuration-error")


def test_active_graph_error_is_the_root() -> None:
    """Every category base inherits from ``ActiveGraphError``. External
    code catching the root catches every framework error."""
    for cls in (
        ConfigurationError,
        RegistrationError,
        ExecutionError,
        ReplayError,
        StorageError,
        PatternError,
        PackError,
    ):
        assert issubclass(cls, ActiveGraphError), cls


def test_doc_slug_is_unique_per_category() -> None:
    """No two category bases share a ``_doc_slug``. Doc URLs must
    disambiguate categories."""
    slugs = [
        ConfigurationError._doc_slug,
        RegistrationError._doc_slug,
        ExecutionError._doc_slug,
        ReplayError._doc_slug,
        StorageError._doc_slug,
        PatternError._doc_slug,
        PackError._doc_slug,
    ]
    assert len(set(slugs)) == len(slugs)


# ---------- reference category: ReplayError ------------------------------


def test_replay_divergence_inherits_from_replay_error() -> None:
    """The reference leaf is wired into the new hierarchy. PR-B+ checks
    the same property for each migrated category."""
    assert issubclass(ReplayDivergenceError, ReplayError)
    assert issubclass(ReplayDivergenceError, ActiveGraphError)


def test_replay_divergence_preserves_legacy_signature() -> None:
    """CONTRACT v0.5 #7 — ``event_id``, ``expected``, ``actual`` are the
    public attributes. Existing tests access them directly. PR-A
    preserves the signature so the 384 v0–v0.9 tests stay valid."""
    err = ReplayDivergenceError(
        event_id="evt_042",
        expected="prompt_hash=a1b2c3d4e5f60718",
        actual="prompt_hash=z9y8x7w6v5u43210",
    )
    assert err.event_id == "evt_042"
    assert err.expected == "prompt_hash=a1b2c3d4e5f60718"
    assert err.actual == "prompt_hash=z9y8x7w6v5u43210"


def test_replay_divergence_prompt_hash_snapshot() -> None:
    """The high-stakes case: an LLM call's prompt hash drifted. The
    most-fired-during-fork-and-diff variant. Snapshot is exact."""
    err = ReplayDivergenceError(
        event_id="evt_042",
        expected="prompt_hash=a1b2c3d4e5f60718",
        actual="prompt_hash=z9y8x7w6v5u43210",
    )
    assert err.kind == "prompt_hash_mismatch"
    assert err.context["kind"] == "prompt_hash_mismatch"
    _assert_format_compliant(err)
    _check_snapshot("replay_divergence__prompt_hash_mismatch", err)


def test_replay_divergence_type_mismatch_snapshot() -> None:
    """The structural case: behaviors produced a different event type at
    the recorded position. Common when a behavior's ``where`` filter
    changed."""
    err = ReplayDivergenceError(
        event_id="evt_113",
        expected="object.created",
        actual="patch.applied",
    )
    assert err.kind == "type_mismatch"
    _assert_format_compliant(err)
    _check_snapshot("replay_divergence__type_mismatch", err)


def test_replay_divergence_short_live_snapshot() -> None:
    """Length mismatch, short live re-run: the recorded log had more
    events than the replay produced. Behavior fires were removed
    or short-circuited."""
    err = ReplayDivergenceError(
        event_id="evt_200",
        expected="behavior.completed",
        actual=None,
    )
    assert err.kind == "length_mismatch"
    _assert_format_compliant(err)
    _check_snapshot("replay_divergence__short_live", err)


def test_replay_divergence_extra_live_snapshot() -> None:
    """Length mismatch, extra live event: the replay produced an event
    the recorded log did not. A behavior was added or loosened."""
    err = ReplayDivergenceError(
        event_id="evt_201",
        expected="<no recorded event>",
        actual="event.emitted",
    )
    assert err.kind == "length_mismatch"
    _assert_format_compliant(err)
    _check_snapshot("replay_divergence__extra_live", err)


def test_replay_divergence_doc_url_uses_slug() -> None:
    """The ``More:`` line in every error points at a real doc page. CI
    will validate the URL resolves once the doc site is live (v1.0
    later PR). For now the URL must at least include the slug."""
    err = ReplayDivergenceError(
        event_id="evt_042",
        expected="prompt_hash=abc",
        actual="prompt_hash=def",
    )
    assert err.doc_url.endswith("/errors/replay-divergence-error")
    assert err.doc_url in str(err)


def test_replay_divergence_names_the_event_id() -> None:
    """CONTRACT v1.0 #7 — errors name names. The event id appears in
    the summary line and in the body, not just hidden in a context
    dict."""
    err = ReplayDivergenceError(
        event_id="evt_042",
        expected="prompt_hash=abc",
        actual="prompt_hash=def",
    )
    msg = str(err)
    # Summary line contains the event id.
    first_line = msg.split("\n", 1)[0]
    assert "evt_042" in first_line
    # Body's "What failed" section contains the event id.
    assert "evt_042" in msg.split("What failed:")[1].split("Why:")[0]
    # "How to fix" includes the event id in the suggested command.
    assert "evt_042" in msg.split("How to fix:")[1].split("More:")[0]


# ---------- PR-B: PatternError reference (UnsupportedPatternError) ------


def _parse(pattern: str):
    """Compile a pattern to force raise; returns the exception."""
    from activegraph.runtime.patterns import parse
    return parse(pattern)


def test_unsupported_pattern_inherits_from_pattern_error() -> None:
    """PR-B reference leaf is wired into the v1.0 hierarchy. Multi-
    inherits SyntaxError so user code that catches SyntaxError around
    pattern compilation continues to work."""
    assert issubclass(UnsupportedPatternError, PatternError)
    assert issubclass(UnsupportedPatternError, ActiveGraphError)
    assert issubclass(UnsupportedPatternError, SyntaxError)


def test_unsupported_pattern_preserves_at_attribute() -> None:
    """CONTRACT v0.7 — every raise carries the offending token in `.at`
    so the IDE / linter / log scrubber can highlight it. PR-B preserves
    the attribute through the v1.0 structured constructor."""
    err = UnsupportedPatternError.refused_feature(
        feature="OR",
        workaround="Register two behaviors.",
        at="OR",
    )
    assert err.at == "OR"
    assert err.context["at"] == "OR"


def test_unsupported_pattern_or_in_where_snapshot() -> None:
    """The canonical refused-feature error. Highest-traffic of the v0.7
    refusals (OR is the first thing Cypher users reach for). Recovery
    points at the 'register two behaviors' workaround."""
    err = UnsupportedPatternError.refused_feature(
        feature="OR",
        workaround=(
            "Register two behaviors, one per branch of the disjunction.\n"
            "Both fire independently; if both branches are true for the\n"
            "same event, both behaviors fire (which is usually what you\n"
            "want — OR-then-dedup is not).\n"
            "\n"
            "Example:\n"
            "  Instead of: WHERE c.confidence > 0.7 OR c.severity = 'high'\n"
            "  Register:   one behavior with WHERE c.confidence > 0.7\n"
            "              one behavior with WHERE c.severity = 'high'"
        ),
        why=(
            "OR in WHERE clauses can produce match-set ambiguity at the "
            "trace level: it's hard to tell, after the fact, which branch "
            "of the OR actually triggered. Registering two behaviors keeps "
            "every fire attributable to a specific pattern in the audit "
            "trail. See CONTRACT v0.7 #8."
        ),
        at="OR",
    )
    _assert_format_compliant(err)
    _check_snapshot("unsupported_pattern__or_in_where", err)


def test_unsupported_pattern_variable_length_path_snapshot() -> None:
    """Refused-feature: -[*]- syntax. Common Cypher idiom; the recovery
    explains the unbounded-cost rationale alongside the workaround."""
    with pytest.raises(UnsupportedPatternError) as excinfo:
        _parse("(a:claim)-[*]->(b:evidence)")
    _assert_format_compliant(excinfo.value)
    _check_snapshot("unsupported_pattern__variable_length_path", excinfo.value)


def test_unsupported_pattern_undirected_relationship_snapshot() -> None:
    """Refused-feature: (a)-[:rel]-(b). The recovery explains that
    direction is needed for the audit trail, not just a style choice."""
    with pytest.raises(UnsupportedPatternError) as excinfo:
        _parse("(a:claim)-[:supports]-(b:evidence)")
    _assert_format_compliant(excinfo.value)
    _check_snapshot("unsupported_pattern__undirected_relationship", excinfo.value)


def test_unsupported_pattern_optional_keyword_snapshot() -> None:
    """Refused-feature: OPTIONAL keyword. Tests the per-keyword
    workaround table."""
    with pytest.raises(UnsupportedPatternError) as excinfo:
        _parse("(a:claim) OPTIONAL")
    _assert_format_compliant(excinfo.value)
    _check_snapshot("unsupported_pattern__optional_keyword", excinfo.value)


def test_unsupported_pattern_unexpected_character_snapshot() -> None:
    """Syntax-error: parser cannot tokenize. Tests the syntax_error
    factory and its 'fix the syntax / see docs' recovery prose."""
    with pytest.raises(UnsupportedPatternError) as excinfo:
        _parse("(a:claim) @")
    _assert_format_compliant(excinfo.value)
    _check_snapshot("unsupported_pattern__unexpected_character", excinfo.value)


def test_unsupported_pattern_relationship_type_required_snapshot() -> None:
    """Syntax-error: a relationship without a type. Common typo —
    `(a)-[]->(b)` instead of `(a)-[:type]->(b)`. The recovery shows
    the expected syntax explicitly."""
    with pytest.raises(UnsupportedPatternError) as excinfo:
        _parse("(a:claim)-[]->(b:evidence)")
    _assert_format_compliant(excinfo.value)
    _check_snapshot("unsupported_pattern__relationship_type_required", excinfo.value)


def test_unsupported_pattern_doc_url_uses_slug() -> None:
    err = UnsupportedPatternError.refused_feature(
        feature="OR", workaround="...", at="OR"
    )
    assert err.doc_url.endswith("/errors/unsupported-pattern-error")
    assert err.doc_url in str(err)


def test_unsupported_pattern_names_the_offending_token() -> None:
    """CONTRACT v1.0 #7 — errors name names. The `at` token appears
    in the rendered message (the format includes context dict access
    indirectly via what_failed prose)."""
    err = UnsupportedPatternError.syntax_error(
        what="unexpected character at position 17",
        at="@!",
    )
    msg = str(err)
    assert "@!" in msg
    assert "position 17" in msg


# ---------- PR-C: StorageError category --------------------------------


def test_storage_leaves_inherit_from_storage_error() -> None:
    """Every PR-C leaf is wired into the v1.0 hierarchy."""
    for cls in (
        InvalidStoreURL,
        NonSerializableEventError,
        CorruptedEventPayloadError,
        SchemaVersionMismatch,
        EventNotFoundError,
        DuplicateEventError,
    ):
        assert issubclass(cls, StorageError), cls
        assert issubclass(cls, ActiveGraphError), cls


def test_storage_leaves_preserve_legacy_base_classes() -> None:
    """Multi-inheritance with stdlib base classes preserves the user
    code that catches the builtin around store operations."""
    # NonSerializableEventError used to be a plain TypeError.
    assert issubclass(NonSerializableEventError, TypeError)
    # InvalidStoreURL used to be a plain ValueError.
    assert issubclass(InvalidStoreURL, ValueError)
    # EventNotFoundError multi-inherits KeyError so `except KeyError`
    # around store lookups keeps working.
    assert issubclass(EventNotFoundError, KeyError)
    # DuplicateEventError multi-inherits ValueError for the same reason.
    assert issubclass(DuplicateEventError, ValueError)


def test_invalid_store_url_bare_path_snapshot() -> None:
    """The most common operator mistake — typing the SQLite file path
    without the scheme prefix. The fix is a one-line edit; the error
    should show the exact corrected URL."""
    from activegraph.store import parse_store_url
    with pytest.raises(InvalidStoreURL) as excinfo:
        parse_store_url("/tmp/run.db")
    _assert_format_compliant(excinfo.value)
    _check_snapshot("invalid_store_url__bare_path", excinfo.value)


def test_invalid_store_url_unsupported_scheme_snapshot() -> None:
    """User tries a database the framework doesn't support. The
    recovery enumerates supported schemes and points at the extension
    path (the EventStore protocol)."""
    from activegraph.store import parse_store_url
    with pytest.raises(InvalidStoreURL) as excinfo:
        parse_store_url("mysql://host/dbname")
    _assert_format_compliant(excinfo.value)
    _check_snapshot("invalid_store_url__unsupported_scheme", excinfo.value)


def test_non_serializable_event_snapshot() -> None:
    """A payload containing a Python value the strict adapter can't
    JSON-encode. The recovery names the offending field path and
    suggests three concrete fixes plus the adapter-extension path."""
    from activegraph.store.serde import encode_payload

    class Custom:
        pass

    payload = {"goal": "x", "nested": {"value": Custom()}}
    with pytest.raises(NonSerializableEventError) as excinfo:
        encode_payload(payload)
    _assert_format_compliant(excinfo.value)
    _check_snapshot("non_serializable_event", excinfo.value)


def test_corrupted_event_payload_snapshot() -> None:
    """Stored JSON that doesn't parse. Recovery prose points at how to
    inspect surrounding events and at the manual-repair path, without
    referencing CLI flags that don't exist yet."""
    from activegraph.store.serde import decode_payload
    with pytest.raises(CorruptedEventPayloadError) as excinfo:
        decode_payload('{"goal": "x", "broken":')
    _assert_format_compliant(excinfo.value)
    _check_snapshot("corrupted_event_payload", excinfo.value)


def test_schema_version_mismatch_snapshot() -> None:
    """The store was written by a different activegraph build. Recovery
    enumerates three concrete actions (upgrade, migrate, drop)."""
    from activegraph import __version__ as _aw_version
    err = SchemaVersionMismatch(
        f"sqlite store schema_version '99' does not match this build's expected '1'",
        what_failed=(
            f"The SQLite store records schema_version='99' in its meta table, "
            f"but activegraph {_aw_version} expects schema_version='1'."
        ),
        why=(
            "The store file format evolves with the framework. The runtime "
            "refuses to read a store with a different schema_version rather "
            "than risk silent data loss — a newer framework might interpret "
            "columns differently than the writer did, and an older framework "
            "might drop fields it doesn't recognize. Either direction would "
            "corrupt the audit trail."
        ),
        how_to_fix=(
            f"One of three actions:\n"
            f"  1. Install the activegraph version that wrote this store\n"
            f"     (whichever shipped schema_version='99').\n"
            f"  2. Migrate the run to a store written by this build:\n"
            f"     activegraph migrate <src-url> <new-dst-url>\n"
            f"     The destination is written with the current schema.\n"
            f"  3. If the store is empty or expendable, delete and re-run.\n"
            f"\n"
            f"Schema version history is documented in CHANGELOG.md."
        ),
        context={
            "found_version": "99",
            "expected_version": "1",
            "activegraph_version": _aw_version,
            "driver": "sqlite",
        },
    )
    _assert_format_compliant(err)
    _check_snapshot("schema_version_mismatch", err)


def test_event_not_found_snapshot() -> None:
    """The high-traffic store lookup error. Fires from inspect, fork,
    causal-chain, basically every operator command that names an event
    id. Recovery points at `activegraph inspect ... --tail` so the
    operator can see which ids actually exist."""
    from activegraph.store import InMemoryEventStore
    store = InMemoryEventStore(run_id="run_test")
    with pytest.raises(EventNotFoundError) as excinfo:
        list(store.iter_events(after="evt_does_not_exist"))
    _assert_format_compliant(excinfo.value)
    _check_snapshot("event_not_found", excinfo.value)


def test_event_not_found_is_a_key_error() -> None:
    """User code catching KeyError around store lookups keeps working."""
    from activegraph.store import InMemoryEventStore
    store = InMemoryEventStore(run_id="run_test")
    with pytest.raises(KeyError):
        list(store.iter_events(after="evt_does_not_exist"))


def test_duplicate_event_snapshot() -> None:
    """Hand-constructed events colliding on id. Voice frames this as
    a programmer error (the id generator is monotonic in normal use)."""
    from activegraph import Event
    from activegraph.store import InMemoryEventStore
    store = InMemoryEventStore(run_id="run_test")
    e1 = Event(id="evt_001", type="goal.created", payload={}, timestamp="2026-05-17T00:00:00Z")
    e2 = Event(id="evt_001", type="goal.created", payload={}, timestamp="2026-05-17T00:00:01Z")
    store.append(e1)
    with pytest.raises(DuplicateEventError) as excinfo:
        store.append(e2)
    _assert_format_compliant(excinfo.value)
    _check_snapshot("duplicate_event", excinfo.value)


def test_duplicate_event_is_a_value_error() -> None:
    """User code catching ValueError around appends keeps working."""
    from activegraph import Event
    from activegraph.store import InMemoryEventStore
    store = InMemoryEventStore(run_id="run_test")
    e1 = Event(id="evt_001", type="goal.created", payload={}, timestamp="2026-05-17T00:00:00Z")
    store.append(e1)
    with pytest.raises(ValueError):
        store.append(e1)


# ---------- PR-D: ExecutionError category ------------------------------


def test_exec_leaves_inherit_from_execution_error() -> None:
    """Every PR-D leaf is wired into the v1.0 hierarchy."""
    for cls in (LLMBehaviorError, ToolError, UnknownToolError, ApprovalNotFoundError):
        assert issubclass(cls, ExecutionError), cls
        assert issubclass(cls, ActiveGraphError), cls


def test_exec_leaves_preserve_legacy_base_classes() -> None:
    """The carriers and lookup error preserve back-compat classes:
    ToolError stays Exception; UnknownToolError keeps RuntimeError;
    ApprovalNotFoundError keeps LookupError."""
    assert issubclass(UnknownToolError, RuntimeError)
    assert issubclass(ApprovalNotFoundError, LookupError)


def test_llm_behavior_error_preserves_reason_signature() -> None:
    """CONTRACT v0.6 #11 — the (reason, message, payload_extras)
    constructor is the wire contract between LLM providers and the
    runtime's behavior.failed event. PR-D preserves the signature so
    the ~8 internal raise sites in providers do not need to change."""
    err = LLMBehaviorError(
        "llm.parse_error",
        "no JSON found",
        payload_extras={"raw_text": "<...>"},
    )
    assert err.reason == "llm.parse_error"
    assert err.payload_extras == {"raw_text": "<...>"}
    assert err.context["reason"] == "llm.parse_error"
    assert err.context["payload_extras"] == {"raw_text": "<...>"}


def test_tool_error_preserves_reason_signature() -> None:
    err = ToolError(
        "tool.timeout",
        "took 31s, exceeds 30s ceiling",
        payload_extras={"elapsed_seconds": 31.0},
    )
    assert err.reason == "tool.timeout"
    assert err.payload_extras == {"elapsed_seconds": 31.0}


def test_llm_behavior_error_parse_error_snapshot() -> None:
    """The highest-traffic LLM failure mode — the model returned
    something that wasn't JSON. Recovery names both fixture and live
    cases."""
    err = LLMBehaviorError(
        "llm.parse_error",
        "Expecting value: line 1 column 1 (char 0)",
    )
    _assert_format_compliant(err)
    _check_snapshot("llm_behavior_error__parse_error", err)


def test_llm_behavior_error_schema_violation_snapshot() -> None:
    """The structural LLM failure — JSON parsed, but didn't match the
    declared output_schema. Recovery walks through the typical fix
    paths."""
    err = LLMBehaviorError(
        "llm.schema_violation",
        "ClaimList: claims.0.confidence: Input should be a valid number",
    )
    _assert_format_compliant(err)
    _check_snapshot("llm_behavior_error__schema_violation", err)


def test_llm_behavior_error_fixture_missing_snapshot() -> None:
    """The fork-and-replay failure — the recorded provider has no
    matching fixture. Recovery walks through the re-recording flow."""
    err = LLMBehaviorError(
        "llm.fixture_missing",
        "no recorded fixture for prompt_hash=a1b2c3d4 in /tmp/fixtures",
    )
    _assert_format_compliant(err)
    _check_snapshot("llm_behavior_error__fixture_missing", err)


def test_llm_behavior_error_unknown_reason_uses_fallback() -> None:
    """A reason code outside the table still produces a format-compliant
    message via the fallback prose."""
    err = LLMBehaviorError(
        "llm.custom_provider_error",
        "model returned 503",
    )
    _assert_format_compliant(err)
    assert "llm.custom_provider_error" in str(err)


def test_tool_error_timeout_snapshot() -> None:
    """The canonical tool failure — exceeded declared timeout. Recovery
    explains the trade-off between raising the timeout vs. retrying in
    the calling behavior."""
    err = ToolError(
        "tool.timeout",
        "fetch_company_docs took 35.2s, exceeds 30s ceiling",
    )
    _assert_format_compliant(err)
    _check_snapshot("tool_error__timeout", err)


def test_tool_error_execution_error_snapshot() -> None:
    """The catch-all tool failure — body raised. Recovery points at
    payload_extras for the original exception."""
    err = ToolError(
        "tool.execution_error",
        "TypeError: unsupported operand type(s) for +: 'NoneType' and 'int'",
    )
    _assert_format_compliant(err)
    _check_snapshot("tool_error__execution_error", err)


def test_unknown_tool_error_snapshot() -> None:
    """The LLM asked for a tool the behavior didn't declare. Recovery
    enumerates the declared tools so the operator can see the mismatch
    without grep-ing source."""
    err = UnknownToolError(
        "LLM called tool 'web_search' which is not declared on @llm_behavior(tools=[...])",
        tool_name="web_search",
        behavior_name="diligence.researcher",
        declared_tools=("diligence.fetch_company_docs", "diligence.fetch_filings"),
    )
    _assert_format_compliant(err)
    _check_snapshot("unknown_tool_error", err)


def test_approval_not_found_snapshot() -> None:
    """Pending-approval lookup miss. Recovery points at rt.pending_approvals()
    and the diligence demo's canonical pattern."""
    err = ApprovalNotFoundError("approval_999", pending_count=2)
    _assert_format_compliant(err)
    _check_snapshot("approval_not_found", err)


def test_approval_not_found_is_a_lookup_error() -> None:
    """User code catching LookupError around the approval API keeps
    working."""
    err = ApprovalNotFoundError("approval_999", pending_count=0)
    assert isinstance(err, LookupError)
