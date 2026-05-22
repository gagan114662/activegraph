"""T4 failing tests for provider-native tool parity fixtures.

These tests use fake SDK clients, not live network and not a runtime-only
scripted provider. They bind D-3 ``inner:2f82f19`` and Sasha second-pass
``inner:12f71bf``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel

from activegraph import (
    FrozenClock,
    Graph,
    IDGen,
    Runtime,
    clear_registry,
    clear_tool_registry,
    llm_behavior,
    tool,
)
from activegraph.llm import AnthropicProvider, OpenAIProvider


Case = Literal["happy", "invalid_args", "unknown_tool", "final_parse_failure"]


class _LookupArgs(BaseModel):
    query: str


class _LookupResult(BaseModel):
    answer: str


class _Answer(BaseModel):
    answer: str


@dataclass
class _RunResult:
    graph: Graph
    client: Any


class _AnthropicMessages:
    def __init__(self, case: Case) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses = _anthropic_responses(case)

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self._responses.pop(0)


class _OpenAICompletions:
    def __init__(self, case: Case) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses = _openai_responses(case)

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self._responses.pop(0)


def _anthropic_client(case: Case) -> SimpleNamespace:
    return SimpleNamespace(messages=_AnthropicMessages(case))


def _openai_client(case: Case) -> SimpleNamespace:
    return SimpleNamespace(
        chat=SimpleNamespace(completions=_OpenAICompletions(case))
    )


def _anthropic_responses(case: Case) -> list[SimpleNamespace]:
    args: Any
    name = "lookup_fact"
    if case == "invalid_args":
        args = {}
    else:
        args = {"query": "alpha"}
    if case == "unknown_tool":
        name = "undeclared_lookup"

    first = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text=""),
            SimpleNamespace(
                type="tool_use",
                id="call_1",
                name=name,
                input=args,
            ),
        ],
        usage=SimpleNamespace(input_tokens=5, output_tokens=2),
        model="claude-sonnet-4-5",
        stop_reason="tool_use",
    )
    if case == "unknown_tool" or case == "invalid_args":
        return [first]
    final_text = "not json" if case == "final_parse_failure" else '{"answer":"alpha fact"}'
    final = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=final_text)],
        usage=SimpleNamespace(input_tokens=6, output_tokens=3),
        model="claude-sonnet-4-5",
        stop_reason="end_turn",
    )
    return [first, final]


def _openai_responses(case: Case) -> list[SimpleNamespace]:
    args = {} if case == "invalid_args" else {"query": "alpha"}
    name = "undeclared_lookup" if case == "unknown_tool" else "lookup_fact"
    first = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call_1",
                            type="function",
                            function=SimpleNamespace(
                                name=name,
                                arguments=json.dumps(args, sort_keys=True),
                            ),
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2),
        model="gpt-4o-mini",
    )
    if case == "unknown_tool" or case == "invalid_args":
        return [first]
    final_text = "not json" if case == "final_parse_failure" else '{"answer":"alpha fact"}'
    final = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=final_text),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=6, completion_tokens=3),
        model="gpt-4o-mini",
    )
    return [first, final]


def _fresh_graph() -> Graph:
    return Graph(ids=IDGen(), clock=FrozenClock("2026-05-22T12:00:00Z"), run_id="t4")


def _register_behavior() -> None:
    @tool(
        name="lookup_fact",
        description="Look up a fact.",
        input_schema=_LookupArgs,
        output_schema=_LookupResult,
        deterministic=True,
    )
    def lookup_fact(args: _LookupArgs, ctx: Any) -> _LookupResult:
        return _LookupResult(answer=f"{args.query} fact")

    @llm_behavior(
        name="answer_with_tool",
        on=["goal.created"],
        description="Answer with one tool call.",
        output_schema=_Answer,
        tools=[lookup_fact],
        max_tool_turns=2,
        temperature=0.0,
    )
    def answer_with_tool(event: Any, graph: Any, ctx: Any, out: _Answer) -> None:
        graph.add_object("answer", {"answer": out.answer})


def _run_provider(provider_name: Literal["anthropic", "openai"], case: Case) -> _RunResult:
    clear_registry()
    clear_tool_registry()
    _register_behavior()
    graph = _fresh_graph()
    if provider_name == "anthropic":
        client = _anthropic_client(case)
        provider = AnthropicProvider(client=client)
    else:
        client = _openai_client(case)
        provider = OpenAIProvider(client=client)
    Runtime(graph, llm_provider=provider, budget={"max_tool_calls": 4}).run_goal("g")
    return _RunResult(graph=graph, client=client)


def _normalized_events(graph: Graph) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for event in graph.events:
        if event.type == "goal.created":
            out.append({"type": event.type})
        elif event.type.startswith("llm."):
            out.append(
                {
                    "type": event.type,
                    "behavior": event.payload.get("behavior"),
                    "turn_index": event.payload.get("turn_index"),
                }
            )
        elif event.type == "tool.requested":
            out.append(
                {
                    "type": event.type,
                    "behavior": event.payload.get("behavior"),
                    "tool": event.payload.get("tool"),
                    "args": event.payload.get("args"),
                    "args_hash": event.payload.get("args_hash"),
                    "call_id": event.payload.get("call_id"),
                }
            )
        elif event.type == "tool.responded":
            error = event.payload.get("error")
            out.append(
                {
                    "type": event.type,
                    "behavior": event.payload.get("behavior"),
                    "tool": event.payload.get("tool"),
                    "args_hash": event.payload.get("args_hash"),
                    "error": error.get("reason") if isinstance(error, dict) else None,
                }
            )
        elif event.type == "object.created" and event.payload["object"]["type"] == "answer":
            out.append(
                {
                    "type": event.type,
                    "object_type": "answer",
                    "data": event.payload["object"]["data"],
                }
            )
        elif event.type == "behavior.failed":
            out.append(
                {
                    "type": event.type,
                    "behavior": event.payload.get("behavior"),
                    "reason": event.payload.get("reason"),
                }
            )
    return out


def _event_types(graph: Graph) -> list[str]:
    return [item["type"] for item in _normalized_events(graph)]


def _terminal_reason(graph: Graph) -> str | None:
    failures = [e for e in graph.events if e.type == "behavior.failed"]
    if not failures:
        return None
    return failures[-1].payload.get("reason")


def test_same_tool_behavior_matches_anthropic_and_openai_event_streams() -> None:
    anthropic = _run_provider("anthropic", "happy")
    openai = _run_provider("openai", "happy")

    assert _normalized_events(anthropic.graph) == _normalized_events(openai.graph)
    assert _event_types(openai.graph) == [
        "goal.created",
        "llm.requested",
        "llm.responded",
        "tool.requested",
        "tool.responded",
        "llm.requested",
        "llm.responded",
        "object.created",
    ]
    assert len(openai.client.chat.completions.calls) == 2
    call_2_messages = openai.client.chat.completions.calls[1]["messages"]
    assert call_2_messages[-2]["role"] == "assistant"
    assert call_2_messages[-2]["tool_calls"][0]["id"] == "call_1"
    assert call_2_messages[-1]["role"] == "tool"
    assert call_2_messages[-1]["tool_call_id"] == "call_1"


def test_provider_parity_uses_fresh_graph_fixtures() -> None:
    clear_registry()
    clear_tool_registry()
    graph_a = _fresh_graph()
    graph_b = _fresh_graph()

    assert graph_a is not graph_b
    assert graph_a.run_id == graph_b.run_id == "t4"
    assert graph_a.events == graph_b.events == []
    assert graph_a.all_objects() == graph_b.all_objects() == []


def test_invalid_args_failure_stream_and_reason_match_across_providers() -> None:
    anthropic = _run_provider("anthropic", "invalid_args")
    openai = _run_provider("openai", "invalid_args")

    assert _event_types(anthropic.graph) == [
        "goal.created",
        "llm.requested",
        "llm.responded",
        "tool.requested",
        "tool.responded",
        "behavior.failed",
    ]
    assert _event_types(openai.graph) == _event_types(anthropic.graph)
    assert _terminal_reason(anthropic.graph) == "tool.invalid_input"
    assert _terminal_reason(openai.graph) == "tool.invalid_input"


def _run_openai_with_tool_arguments(arguments: str) -> _RunResult:
    clear_registry()
    clear_tool_registry()
    _register_behavior()
    graph = _fresh_graph()
    first = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call_1",
                            type="function",
                            function=SimpleNamespace(
                                name="lookup_fact",
                                arguments=arguments,
                            ),
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2),
        model="gpt-4o-mini",
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(calls=[], _responses=[first]))
    )

    def create(**kwargs: Any) -> SimpleNamespace:
        client.chat.completions.calls.append(kwargs)
        return client.chat.completions._responses.pop(0)

    client.chat.completions.create = create
    provider = OpenAIProvider(client=client)
    Runtime(graph, llm_provider=provider, budget={"max_tool_calls": 4}).run_goal("g")
    return _RunResult(graph=graph, client=client)


def test_openai_tool_arguments_must_decode_to_object() -> None:
    for arguments in ('"not an object"', "1", '[["query", "alpha"]]'):
        result = _run_openai_with_tool_arguments(arguments)

        assert _event_types(result.graph) == [
            "goal.created",
            "llm.requested",
            "llm.responded",
            "tool.requested",
            "tool.responded",
            "behavior.failed",
        ]
        assert _terminal_reason(result.graph) == "tool.invalid_input"
        assert not [
            e for e in result.graph.events
            if e.type == "object.created"
            and e.payload["object"]["type"] == "answer"
        ]


def test_unknown_tool_failure_stream_and_reason_match_across_providers() -> None:
    anthropic = _run_provider("anthropic", "unknown_tool")
    openai = _run_provider("openai", "unknown_tool")

    assert _event_types(anthropic.graph) == [
        "goal.created",
        "llm.requested",
        "llm.responded",
        "behavior.failed",
    ]
    assert _event_types(openai.graph) == _event_types(anthropic.graph)
    assert _terminal_reason(anthropic.graph) == "tool.unknown_tool"
    assert _terminal_reason(openai.graph) == "tool.unknown_tool"


def test_final_parse_failure_stream_and_reason_match_across_providers() -> None:
    anthropic = _run_provider("anthropic", "final_parse_failure")
    openai = _run_provider("openai", "final_parse_failure")

    assert _event_types(anthropic.graph) == [
        "goal.created",
        "llm.requested",
        "llm.responded",
        "tool.requested",
        "tool.responded",
        "llm.requested",
        "llm.responded",
        "behavior.failed",
    ]
    assert _event_types(openai.graph) == _event_types(anthropic.graph)
    assert _terminal_reason(anthropic.graph) == "llm.parse_error"
    assert _terminal_reason(openai.graph) == "llm.parse_error"
