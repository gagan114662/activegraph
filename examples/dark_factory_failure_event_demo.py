"""Dark-factory dogfooding demo: capture the first live `behavior.failed`
event in this repo using only activegraph's own runtime + a synthetic
provider that always fails.

Why this exists:
  Today, dark-factory failures (Codex credit exhaustion, Pentagon
  ghost_completion, Claude Code session limits, Maya path drift) all
  live in non-activegraph stores: Pentagon's Supabase tables, the
  bridge's stdout log, the T7 ledger JSONL. activegraph itself ships
  full `behavior.failed` machinery (CONTRACT v0.6 #11 + #13, see
  runtime.py) but the repo has never emitted one. This is the first.

What it proves:
  1. A `@llm_behavior` whose provider raises `LLMBehaviorError` produces
     a real `behavior.failed` event with a structured `reason` field.
  2. The event lives in the run's graph, persists to SQLite, and is
     queryable via the same API the rest of activegraph uses.
  3. No API keys, no network calls — just the framework eating its
     own dogfood.

Run: `python examples/dark_factory_failure_event_demo.py`
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from activegraph import Graph, Runtime, behavior, llm_behavior
from activegraph.llm.errors import LLMBehaviorError
from activegraph.llm.types import LLMMessage, LLMResponse


class FailingProvider:
    """Implements `LLMProvider` but every `complete()` raises.

    Mirrors the shape of `_DemoScriptedProvider` in `llm_claim_extraction.py`
    (no API key, no network) but always raises `LLMBehaviorError` with
    `reason="llm.network_error"` — the same code AnthropicProvider would
    raise on a real upstream failure (per `_classify_provider_exception`
    in `activegraph/llm/anthropic.py:298`).
    """

    default_model: str = "synthetic-failing-model"

    def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        model: str,
        max_tokens: int,
        temperature: float,
        top_p: float,
        output_schema: Optional[type],
        timeout_seconds: float,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> LLMResponse:
        extras = {
            "model": model,
            "exception_type": "SyntheticFailure",
            "message": (
                "FailingProvider always raises. Used by the dark-factory "
                "dogfooding demo to capture the repo's first real "
                "`behavior.failed` event."
            ),
            "retry_after_seconds": 0.0,
        }
        raise LLMBehaviorError(
            "llm.network_error",
            "synthetic failure for dark-factory dogfooding demo",
            payload_extras=extras,
        )

    def estimate_cost(
        self, *, input_tokens: int, output_tokens: int, model: str
    ) -> Decimal:
        return Decimal("0")

    def count_tokens(
        self, *, system: str, messages: list[LLMMessage], model: str
    ) -> int:
        # Heuristic so budget gating doesn't depend on a real tokenizer.
        text = system + "".join(m.content for m in messages)
        return max(1, len(text) // 4)

    def recognizes_model(self, name: str) -> bool:
        return name == self.default_model


@behavior(name="seed", on=["goal.created"])
def seed(event, graph, ctx):
    """Create one stub document so the llm_behavior has something to chew on."""
    graph.add_object(
        "document",
        {"title": "stub-for-dark-factory-demo", "body": event.payload["goal"]},
    )


@llm_behavior(
    name="will_fail",
    on=["object.created"],
    where={"object.type": "document"},
    description="Triggers a synthetic LLM call that always fails — captures the first behavior.failed event in this repo.",
    model="synthetic-failing-model",
    view={"around": "event.payload.object.id", "depth": 1},
    creates=[],
    deterministic=True,
)
def will_fail(event, graph, ctx, llm_output):
    # Never reached — provider raises before this handler runs. Body is
    # required because the runtime invokes the handler with llm_output
    # only after a successful provider call.
    raise AssertionError("unreachable: FailingProvider should have raised")


def main() -> None:
    provider = FailingProvider()
    graph = Graph()
    rt = Runtime(
        graph,
        llm_provider=provider,
        budget={"max_llm_calls": 5, "max_cost_usd": "0.10", "max_seconds": 30},
    )
    rt.run_goal("dark-factory dogfooding: produce the first behavior.failed event")

    failures = [e for e in rt.graph.events if e.type == "behavior.failed"]
    print(f"\n=== behavior.failed events captured: {len(failures)} ===")
    for ev in failures:
        print(f"\nevent_id: {ev.id}")
        print(f"  type:    {ev.type}")
        print(f"  reason:  {ev.payload.get('reason')}")
        print(f"  behavior: {ev.payload.get('behavior')}")
        message = ev.payload.get('message') or ev.payload.get('error_message')
        if message:
            print(f"  message: {message}")
        extras_keys = [k for k in ev.payload.keys() if k not in {"reason", "behavior", "message", "error_message"}]
        if extras_keys:
            print(f"  extras:  {sorted(extras_keys)}")

    if not failures:
        print("\nNO behavior.failed events emitted — runtime swallowed the error somewhere upstream.")
        raise SystemExit(2)

    print(f"\nTotal events in run: {len(rt.graph.events)}")
    print(f"Event type histogram: { {t: sum(1 for e in rt.graph.events if e.type == t) for t in sorted({e.type for e in rt.graph.events})} }")


if __name__ == "__main__":
    main()
