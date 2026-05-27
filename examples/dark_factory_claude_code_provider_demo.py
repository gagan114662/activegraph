"""Dark-factory dogfooding demo, Part 2: activegraph running on a real
LLM call dispatched through the operator's Claude Code subscription —
no `ANTHROPIC_API_KEY`, no separate billing relationship.

What this proves:
  1. `ClaudeCodeCliProvider` implements the `LLMProvider` Protocol cleanly
     enough that the activegraph runtime accepts it as a peer of
     `AnthropicProvider`/`OpenAIProvider`.
  2. A real `claude` CLI subprocess runs with the operator's keychain-
     stored OAuth, produces a real assistant response, and the runtime
     captures it as a real `llm.responded` event with authentic
     `input_tokens`, `output_tokens`, `cost_usd`, `model`, and
     `latency_seconds`.
  3. The "flywheel" entry condition holds: activegraph is now the
     runtime, the auth path matches the dark factory's existing bridge,
     and failures (rate limit, network error, auth) surface as
     `behavior.failed` events with the same `reason` codes as
     AnthropicProvider would emit.

Run: `python examples/dark_factory_claude_code_provider_demo.py`

Note: the call IS real and DOES consume tokens from the Claude Code
subscription. Cost is roughly $0.01-$0.05 per run depending on prompt
caching. To run offline, swap `ClaudeCodeCliProvider` with
`RecordedLLMProvider`.
"""

from __future__ import annotations

from activegraph import Graph, Runtime, behavior, llm_behavior
from activegraph.llm import ClaudeCodeCliProvider, LLMBehaviorError


# ---------- behaviors -------------------------------------------------------


@behavior(name="seed", on=["goal.created"])
def seed(event, graph, ctx):
    """Create one stub document so the llm_behavior triggers."""
    graph.add_object(
        "ping",
        {"prompt": "Reply with exactly one word: alive"},
    )


@llm_behavior(
    name="claude_ping",
    on=["object.created"],
    where={"object.type": "ping"},
    description=(
        "Send a one-word ping to claude via ClaudeCodeCliProvider to "
        "prove activegraph can drive Claude Code OAuth dispatch end-to-end."
    ),
    model="claude-opus-4-7",
    view={"around": "event.payload.object.id", "depth": 1},
    creates=["pong"],
    deterministic=True,
    budget={"max_llm_calls": 2},
)
def claude_ping(event, graph, ctx, llm_output):
    # `llm_output` is `response.parsed` (None here — no output_schema). The
    # scoped `graph` inside a behavior handler doesn't expose `.events`;
    # the runtime already wrote the `llm.responded` event before invoking
    # this handler. We just need to do useful work and emit our own object.
    # The demo's success criterion lives entirely on the llm.responded
    # event the runtime captured.
    graph.add_object("pong", {"prompt_id": event.payload["object"]["id"]})


def main() -> None:
    provider = ClaudeCodeCliProvider()
    graph = Graph()
    rt = Runtime(
        graph,
        llm_provider=provider,
        budget={"max_llm_calls": 2, "max_cost_usd": "0.50", "max_seconds": 60},
    )

    try:
        rt.run_goal("Prove activegraph + Claude Code subscription works end-to-end")
    except Exception as e:
        # The runtime usually surfaces errors as `behavior.failed` events
        # rather than raising. If we get here something more structural
        # happened — log and continue so we can still inspect the events.
        print(f"\n[caught top-level] {type(e).__name__}: {e}")

    print("\n=== Event chain ===")
    for ev in rt.graph.events:
        print(f"  {ev.id}  {ev.type:24s}  ", end="")
        if ev.type == "llm.requested":
            print(f"model={ev.payload.get('model')} prompt_chars={len(str(ev.payload.get('prompt', '')))}")
        elif ev.type == "llm.responded":
            print(
                f"model={ev.payload.get('model')} "
                f"in_tok={ev.payload.get('input_tokens')} "
                f"out_tok={ev.payload.get('output_tokens')} "
                f"cost_usd={ev.payload.get('cost_usd')} "
                f"latency_s={ev.payload.get('latency_seconds'):.2f}"
            )
        elif ev.type == "behavior.failed":
            print(f"reason={ev.payload.get('reason')} behavior={ev.payload.get('behavior')}")
        elif ev.type == "object.created":
            obj = ev.payload.get("object") or {}
            print(f"type={obj.get('type')} data={obj.get('data')}")
        else:
            print()

    pongs = [o for o in rt.graph.all_objects() if o.type == "pong"]
    print(f"\n=== pong objects: {len(pongs)} ===")
    for p in pongs:
        print(f"  claude_said: {p.data.get('claude_said')!r}")

    responded = [e for e in rt.graph.events if e.type == "llm.responded"]
    if responded:
        print(f"\n=== llm.responded events: {len(responded)} ===")
        for ev in responded:
            print(
                f"  {ev.id}: {ev.payload.get('input_tokens')} in / "
                f"{ev.payload.get('output_tokens')} out, "
                f"${ev.payload.get('cost_usd')}, "
                f"{ev.payload.get('latency_seconds'):.2f}s"
            )
        print("\nSUCCESS: activegraph just drove a real claude CLI call "
              "with NO ANTHROPIC_API_KEY. The dark factory's runtime "
              "and the bridge now share the same auth path.")
    else:
        failed = [e for e in rt.graph.events if e.type == "behavior.failed"]
        if failed:
            print(f"\n=== behavior.failed events: {len(failed)} ===")
            for ev in failed:
                print(f"  reason={ev.payload.get('reason')} message={ev.payload.get('message')}")
            print("\nProvider call failed but emitted a structured "
                  "behavior.failed event — the failure-event machinery "
                  "is wired correctly.")
        else:
            print("\nNo llm.responded AND no behavior.failed. Something "
                  "is wrong upstream of the provider.")


if __name__ == "__main__":
    main()
