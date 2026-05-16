"""v0.7 killer demo: tool use + Cypher pattern subscriptions.

This file is the v0.7 contract. The API surface — `@tool`, `tools=`
on `@llm_behavior`, the `ToolContext` shape, the `pattern=` Cypher
subset, `ctx.matches`, `activate_after`, the tool event types — is
locked here first; the runtime is built backward to make it run.
Same discipline as v0/v0.5/v0.6.

What this demo proves:

  1. A `@behavior` (`planner`) bootstraps the run by turning the goal
     into a `goal_record` object.
  2. A `@llm_behavior` (`question_generator`) reacts to the goal_record
     and emits initial research questions — no tools, just structured
     output.
  3. A `@llm_behavior` (`researcher`) reacts to each question and uses
     two tools (`web_fetch`, `graph_query`) in an LLM ↔ tool turn
     loop owned by the runtime. The handler never sees raw tool
     calls; it sees the final parsed `ResearchFindings`.
  4. A pattern-subscribed `@llm_behavior` (`critic`) activates whenever
     the graph contains two high-confidence claims connected by a
     `:contradicts` edge. Cypher subset:
     `(c1:claim)-[r:contradicts]->(c2:claim)
      WHERE c1.confidence > 0.7 AND c2.confidence > 0.7`.
  5. A `@behavior` (`nag`) declares `activate_after=2` (event-count
     model — wall-clock is intentionally out of scope; see CONTRACT
     v0.7 #13). When a task is created, the behavior is scheduled
     for invocation two events later, but only fires if
     `where={"object.data.status": "open"}` still holds at that
     point.
  6. We save the run to SQLite, fork at the goal event with
     `replay_llm_cache=True` AND tool replay enabled. The fork
     rebuilds the same prompts, hits the LLM cache, AND serves every
     tool response from the recorded `tool.responded` events. Zero
     new API calls, zero new tool invocations.
  7. Both traces print, including the new `[tool.requested]`,
     `[tool.responded]`, `[pattern.matched]`, and
     `[behavior.scheduled]` lines.
  8. A `causal_chain` query on one of the final claims walks back
     through the LLM call AND every tool call that informed it, all
     the way to the source goal.

The demo ships its own tiny providers so it runs without an API key
or network access. Production usage substitutes `AnthropicProvider`
and a real `web_fetch` tool implementation.

Run it: `python examples/diligence_with_tools.py`
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field

from activegraph import (
    Graph,
    Runtime,
    behavior,
    clear_registry,
    llm_behavior,
)
from activegraph.llm import LLMMessage, LLMResponse, ToolCall
from activegraph.tools import (
    Tool,
    ToolContext,
    clear_tool_registry,
    make_graph_query_tool,
    tool,
)


DB = "/tmp/activegraph_diligence_with_tools.db"


# ---------- structured output schemas --------------------------------------


class ResearchQuestions(BaseModel):
    """The initial set of questions the diligence run will research."""

    questions: list[str] = Field(min_length=1)


class ResearcherClaim(BaseModel):
    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    source_url: Optional[str] = None
    # When the researcher believes its new claim contradicts an existing
    # claim, it returns the existing claim's id here. The handler adds a
    # `:contradicts` edge.
    contradicts_claim_id: Optional[str] = None


class ResearchFindings(BaseModel):
    claims: list[ResearcherClaim]


class Resolution(BaseModel):
    """Critic's adjudication of two contradicting claims."""

    rationale: str
    winning_claim_id: Optional[str] = None  # None → "neither / abstain"


ResearchFindings.model_rebuild()
Resolution.model_rebuild()
ResearcherClaim.model_rebuild()


# ---------- tool I/O schemas -----------------------------------------------


class WebFetchInput(BaseModel):
    url: str
    timeout_seconds: float = 10.0


class WebFetchOutput(BaseModel):
    text: str
    status: int
    final_url: str


# ---------- the web_fetch tool (demo-only scripted body) -------------------


# Demo URL → canned response. A real web_fetch would use urllib /
# httpx; we keep it offline so the demo and its CI test require no
# network access. Real production: see `activegraph.tools.web_fetch`.
_WEB_FIXTURES: dict[str, dict[str, Any]] = {
    "https://example.com/q3-sales": {
        "text": (
            "Q3 sales results show 14% YoY growth in the SMB segment, while "
            "enterprise contracts declined 3% over the same period."
        ),
        "status": 200,
    },
    "https://example.com/model-card-v4": {
        "text": (
            "The v4 model achieves a 22% relative improvement on GSM8K over "
            "our previous best, with no regression on HumanEval."
        ),
        "status": 200,
    },
    "https://example.com/retention-rumors": {
        "text": (
            "Some users have reported retention slipping a bit in recent "
            "months, but hard numbers are not yet available."
        ),
        "status": 200,
    },
}


@tool(
    name="web_fetch_demo",
    description="Fetch the body text of a URL. Returns text, HTTP status, and final URL after redirects.",
    input_schema=WebFetchInput,
    output_schema=WebFetchOutput,
    cost_per_call=Decimal("0.001"),
    timeout_seconds=10.0,
    deterministic=False,
)
def web_fetch_demo(args: WebFetchInput, ctx: ToolContext) -> WebFetchOutput:
    fixture = _WEB_FIXTURES.get(args.url)
    if fixture is None:
        return WebFetchOutput(text="", status=404, final_url=args.url)
    return WebFetchOutput(
        text=fixture["text"], status=fixture["status"], final_url=args.url
    )


# ---------- demo provider that knows how to call tools ---------------------


# Maps question text fragment → the URL the LLM "wants" to fetch, plus
# the final claims to emit. The provider returns a tool_call on the
# first turn and the parsed structured output on the second turn.
_RESEARCH_PLAN: dict[str, dict[str, Any]] = {
    "Q3": {
        "fetch_url": "https://example.com/q3-sales",
        "claims": [
            {
                "text": "SMB segment grew 14% YoY in Q3.",
                "confidence": 0.9,
                "source_url": "https://example.com/q3-sales",
            },
            {
                "text": "Enterprise contracts declined 3% in Q3.",
                "confidence": 0.85,
                "source_url": "https://example.com/q3-sales",
            },
        ],
    },
    "Model": {
        "fetch_url": "https://example.com/model-card-v4",
        "claims": [
            {
                "text": "v4 model improves GSM8K by 22% over the prior best.",
                "confidence": 0.9,
                "source_url": "https://example.com/model-card-v4",
            },
        ],
    },
    "retention": {
        "fetch_url": "https://example.com/retention-rumors",
        "claims": [
            # This contradicts the SMB-growth optimism above when both
            # are high confidence (>0.7). The critic should activate
            # via the pattern subscription. The id is filled in at
            # runtime by `_inject_contradiction_target` once the
            # researcher has seen the graph_query result that names
            # the SMB-growth claim — in a real demo, the LLM would
            # decide; here we cheat for determinism.
            {
                "text": "Retention is materially declining in recent months.",
                "confidence": 0.75,
                "source_url": "https://example.com/retention-rumors",
                "contradicts_claim_id": None,  # filled in dynamically below
            },
        ],
    },
}


_QUESTIONS = [
    "What were the Q3 sales results?",
    "Model performance update?",
    "Any retention concerns?",
]


class _DemoProvider:
    """Scripted provider — implements the v0.7 LLMProvider protocol.

    Decides what to return by inspecting `messages` and `tools`:
      - For the question_generator (no tools), returns the three
        questions immediately as parsed structured output.
      - For the researcher (tools=[web_fetch_demo, graph_query]):
        turn 1 returns a tool_call to web_fetch_demo;
        turn 2 returns a tool_call to graph_query;
        turn 3 returns the final ResearchFindings.
      - For the critic (no tools), returns a Resolution.
    """

    def complete(
        self,
        *,
        system,
        messages,
        model,
        max_tokens,
        temperature,
        top_p,
        output_schema,
        timeout_seconds,
        tools=None,
    ) -> LLMResponse:
        last_user = next(
            (m.content for m in reversed(messages) if m.role == "user"), ""
        )

        # ---- question_generator path ----
        if "Generate" in (system or "") or output_schema is ResearchQuestions:
            return _resp(
                model,
                output_schema,
                {"questions": _QUESTIONS},
            )

        # ---- critic path (pattern-matched) ----
        if output_schema is Resolution:
            return _resp(
                model,
                output_schema,
                {
                    "rationale": (
                        "Retention concerns and SMB growth are not strictly "
                        "incompatible — segment-level growth can co-exist "
                        "with cohort-level retention decline. Marking the "
                        "lower-confidence claim as the loser."
                    ),
                    # The pattern bindings expose ids; the LLM doesn't
                    # see them in this demo's scripted response.
                    "winning_claim_id": None,
                },
            )

        # ---- researcher path: orchestrate the turn loop ----
        plan_key = _researcher_plan_key(last_user)
        plan = _RESEARCH_PLAN.get(plan_key)
        if plan is None:
            raise RuntimeError(
                f"researcher: no scripted plan for question:\n{last_user[:200]!r}"
            )
        # Inspect message history to figure out which turn we're on.
        turn = _researcher_turn(messages, plan)
        if turn == 1:
            return _tool_call(
                model,
                tool_name="web_fetch_demo",
                args={"url": plan["fetch_url"], "timeout_seconds": 10.0},
            )
        if turn == 2:
            return _tool_call(
                model,
                tool_name="graph_query",
                args={"object_type": "claim"},
            )
        # turn 3: final answer. For the retention plan, look up the
        # SMB-growth claim from the most-recent graph_query result so
        # we can mark a real contradiction.
        claims_out = [dict(c) for c in plan["claims"]]
        if plan_key == "retention":
            for c in claims_out:
                if c.get("contradicts_claim_id") is None:
                    c["contradicts_claim_id"] = _find_smb_claim_id(messages)
        return _resp(
            model,
            output_schema,
            {"claims": claims_out},
        )

    def estimate_cost(self, *, input_tokens, output_tokens, model) -> Decimal:
        return Decimal("0.0012")

    def count_tokens(self, *, system, messages, model) -> int:
        total = len(system or "") + sum(len(m.content) for m in messages)
        return max(1, total // 4)


def _researcher_plan_key(user_text: str) -> Optional[str]:
    """Find the plan whose key appears in the TRIGGERING EVENT section.

    The view block lists every question, so a naive substring match
    returns the first listed plan instead of the one for the question
    that actually fired. Scope to the triggering-event section.
    """
    marker = "## Triggering event"
    if marker in user_text:
        trig = user_text.split(marker, 1)[1]
    else:
        trig = user_text
    for key in _RESEARCH_PLAN:
        if key.lower() in trig.lower():
            return key
    return None


def _find_smb_claim_id(messages) -> Optional[str]:
    """Inspect graph_query tool results to find the SMB growth claim id.

    The result message content is JSON: `{"refs": [{"id": "claim#6",
    "type": "claim", "data": {"text": "SMB segment grew ..."}}, ...]}`.
    Returns the id whose text mentions "SMB" / "growth"; None if not found.
    """
    for m in messages:
        if m.role != "tool" or m.tool_name != "graph_query":
            continue
        try:
            payload = json.loads(m.content)
        except Exception:
            continue
        for ref in payload.get("refs", []):
            text = (ref.get("data") or {}).get("text") or ""
            if "SMB" in text or "smb" in text.lower():
                return ref.get("id")
    return None


def _researcher_turn(messages, plan) -> int:
    """1 = first tool call; 2 = second tool call; 3 = final answer.

    Detect prior tool turns by inspecting role="tool" messages — these
    are echoed back into the conversation by the runtime's turn loop.
    """
    fetched = any(
        m.role == "tool" and m.tool_name == "web_fetch_demo"
        for m in messages
    )
    queried = any(
        m.role == "tool" and m.tool_name == "graph_query"
        for m in messages
    )
    if not fetched:
        return 1
    if not queried:
        return 2
    return 3


def _resp(model: str, output_schema: type, payload: dict) -> LLMResponse:
    raw = json.dumps(payload, sort_keys=True)
    parsed = output_schema.model_validate(payload) if output_schema else None
    return LLMResponse(
        raw_text=raw,
        parsed=parsed,
        input_tokens=120,
        output_tokens=24,
        cost_usd=Decimal("0.0012"),
        latency_seconds=0.5,
        model=model,
        finish_reason="end_turn",
    )


def _tool_call(model: str, tool_name: str, args: dict) -> LLMResponse:
    call = ToolCall(id=f"call_{tool_name}", name=tool_name, args=args)
    return LLMResponse(
        raw_text="",
        parsed=None,
        input_tokens=110,
        output_tokens=18,
        cost_usd=Decimal("0.0008"),
        latency_seconds=0.4,
        model=model,
        finish_reason="tool_use",
        tool_calls=[call],
    )


# ---------- behaviors -------------------------------------------------------


def _register_behaviors(graph: Graph) -> Tool:
    """Register tools and behaviors. Behaviors are code, not state.

    Returns the bound graph_query tool so the caller can pass it into
    `@llm_behavior(tools=[...])`.
    """

    clear_registry()
    clear_tool_registry()

    # graph_query is bound to a specific Graph via factory (CONTRACT
    # v0.7 #5 / #16). web_fetch_demo is decorated at module load.
    graph_query = make_graph_query_tool(graph)

    @behavior(name="planner", on=["goal.created"])
    def planner(event, graph, ctx):
        graph.add_object(
            "goal_record", {"text": event.payload.get("goal", "")}
        )
        # Also produce a single "task" to exercise the activate_after
        # nag behavior.
        graph.add_object(
            "task", {"title": "Compile final brief", "status": "open"}
        )

    @llm_behavior(
        name="question_generator",
        on=["object.created"],
        where={"object.type": "goal_record"},
        description="Generate the initial research questions for this goal.",
        model="claude-sonnet-4-5",
        output_schema=ResearchQuestions,
        creates=["question"],
        deterministic=True,
    )
    def question_generator(event, graph, ctx, out):
        for q in out.questions:
            graph.add_object("question", {"text": q, "status": "open"})

    @llm_behavior(
        name="researcher",
        on=["object.created"],
        where={"object.type": "question"},
        description=(
            "Research the question. Call web_fetch_demo to gather source "
            "material and graph_query to check for existing related claims. "
            "Then emit a list of claims with confidence scores; mark "
            "contradictions explicitly via contradicts_claim_id."
        ),
        model="claude-sonnet-4-5",
        output_schema=ResearchFindings,
        tools=[web_fetch_demo, graph_query],
        creates=["claim"],
        deterministic=True,
        budget={"max_tool_calls": 8},
    )
    def researcher(event, graph, ctx, out):
        qid = event.payload["object"]["id"]
        for c in out.claims:
            cobj = graph.add_object(
                "claim",
                {
                    "text": c.text,
                    "confidence": c.confidence,
                    "source_url": c.source_url,
                    "status": "open",
                },
            )
            graph.add_relation(cobj.id, qid, "addresses")
            if c.contradicts_claim_id and graph.get_object(c.contradicts_claim_id):
                graph.add_relation(
                    cobj.id, c.contradicts_claim_id, "contradicts"
                )

    @llm_behavior(
        name="critic",
        # Scope to relation.created of contradicts edges so the critic
        # fires ONCE per new `:contradicts` edge — not once per
        # subsequent event after the edge exists. Per CONTRACT v0.7
        # #11, ALL of `on=`, `where=`, AND `pattern=` must hold.
        on=["relation.created"],
        where={"relation.type": "contradicts"},
        pattern=(
            "(c1:claim)-[r:contradicts]->(c2:claim) "
            "WHERE c1.confidence > 0.7 AND c2.confidence > 0.7"
        ),
        description="Resolve a contradiction between two high-confidence claims.",
        model="claude-sonnet-4-5",
        output_schema=Resolution,
        creates=["resolution"],
        deterministic=True,
    )
    def critic(event, graph, ctx, out):
        for m in ctx.matches:
            graph.add_object(
                "resolution",
                {
                    "rationale": out.rationale,
                    "winning_claim_id": out.winning_claim_id,
                    "between": [m["c1"], m["c2"]],
                },
            )

    @behavior(
        name="nag",
        on=["object.created"],
        where={"object.type": "task"},
        activate_after=2,
    )
    def nag(event, graph, ctx):
        task_id = event.payload["object"]["id"]
        obj = graph.get_object(task_id)
        if obj is None or obj.data.get("status") != "open":
            return  # CONTRACT v0.7 #13: where re-checked at fire time
        graph.add_object(
            "escalation",
            {"task_id": task_id, "reason": "task still open after 2 events"},
        )

    return graph_query


# ---------- demo flow -------------------------------------------------------


def step_1_run() -> Runtime:
    if os.path.exists(DB):
        os.remove(DB)
    graph = Graph()
    _register_behaviors(graph)
    provider = _DemoProvider()
    rt = Runtime(
        graph,
        llm_provider=provider,
        persist_to=DB,
        budget={
            "max_llm_calls": 20,
            "max_tool_calls": 30,
            "max_cost_usd": "1.00",
        },
    )
    rt.run_goal("Diligence: Q3 + model + retention")
    rt.save_state()
    n_claims = sum(1 for o in rt.graph.all_objects() if o.type == "claim")
    n_resolutions = sum(
        1 for o in rt.graph.all_objects() if o.type == "resolution"
    )
    n_tools = sum(1 for e in rt.graph.events if e.type == "tool.responded")
    print(
        f"[step 1] run {rt.run_id}: "
        f"{n_claims} claims, {n_resolutions} resolutions, {n_tools} tool calls"
    )
    return rt


def step_2_fork_with_caches(parent: Runtime) -> Runtime:
    goal_evt = next(e for e in parent.graph.events if e.type == "goal.created")
    # behaviors are code, not state — re-register against the FORK's graph
    # so graph_query closures hit the right graph.
    parent_provider = parent.llm_provider
    # We'll bind graph_query in a moment via _register_behaviors; the
    # provider is reused (it's stateless).
    fork = parent.fork(
        at_event=goal_evt.id,
        label="cached-replay",
        replay_llm_cache=True,
        replay_tool_cache=True,
        llm_provider=parent_provider,
    )
    _register_behaviors(fork.graph)
    fork.run_until_idle()
    fork.save_state()
    n_llm_cached = _count_cache_hits(fork, "llm.responded")
    n_tool_cached = _count_cache_hits(fork, "tool.responded")
    print(
        f"[step 2] fork {fork.run_id}: "
        f"{n_llm_cached} LLM cache hits, {n_tool_cached} tool cache hits"
    )
    return fork


def step_3_print_traces(parent: Runtime, fork: Runtime) -> None:
    print("\n=== parent trace ===")
    parent.print_trace()
    print("\n=== fork trace (replay_llm_cache + replay_tool_cache) ===")
    fork.print_trace()


def step_4_causal_chain(parent: Runtime) -> None:
    first_claim = next(
        (o for o in parent.graph.all_objects() if o.type == "claim"), None
    )
    if first_claim is None:
        print("\n(no claims produced; skipping causal chain)")
        return
    print(f"\n=== causal chain for {first_claim.id} ===")
    print(parent.trace.causal_chain(first_claim.id))


def _count_cache_hits(rt: Runtime, event_type: str) -> int:
    return sum(
        1
        for e in rt.graph.events
        if e.type == event_type and e.payload.get("cache_hit") is True
    )


if __name__ == "__main__":
    parent = step_1_run()
    fork = step_2_fork_with_caches(parent)
    step_3_print_traces(parent, fork)
    step_4_causal_chain(parent)
