"""v1.0.3 #4: multi-turn tool-use messages carry full content blocks.

The bug: when the LLM returned tool_use blocks, the runtime appended
only `raw_text` to the message history. Anthropic's API spec requires
every tool_result block in a following user message to reference a
tool_use_id from a tool_use block in the preceding assistant message.
The raw-text-only echo dropped those blocks and produced spec-
violating messages — tolerated by direct Anthropic API access,
rejected by the Vertex AI proxy with HTTP 400.

The fix: `LLMMessage.tool_calls` carries the originating `ToolCall`s
alongside the text; `_message_to_anthropic` reconstructs the wire-
format content blocks. Adjacent fix: `_response_from_fixture` now
reconstructs `tool_calls` from fixtures so recorded multi-turn
exchanges round-trip.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import BaseModel

from activegraph import (
    Graph,
    Runtime,
    Tool,
    ToolContext,
    behavior,
    llm_behavior,
    tool,
)
from activegraph.llm import LLMMessage, LLMResponse, ToolCall
from activegraph.llm.anthropic import _message_to_anthropic
from activegraph.llm.recorded import RecordedLLMProvider


# ---------- LLMMessage tool_calls additive field ----------


def test_llmmessage_to_dict_omits_tool_calls_when_none():
    """The hashing-stability invariant: existing single-turn fixtures
    must keep their byte-identical prompt hashes. The field is only
    emitted when non-None so to_dict() output for v0.7 / v1.0.2-style
    messages is unchanged."""
    m = LLMMessage(role="user", content="hi")
    d = m.to_dict()
    assert "tool_calls" not in d
    assert d == {"role": "user", "content": "hi"}


def test_llmmessage_to_dict_emits_tool_calls_when_present():
    m = LLMMessage(
        role="assistant",
        content="thinking",
        tool_calls=(
            ToolCall(id="c1", name="my_tool", args={"q": "x"}),
        ),
    )
    d = m.to_dict()
    assert d["tool_calls"] == [{"id": "c1", "name": "my_tool", "args": {"q": "x"}}]


def test_llmmessage_default_tool_calls_is_none():
    """Backward-compat: code that constructs LLMMessage without
    naming tool_calls keeps its v0.7-shape behavior."""
    m = LLMMessage(role="user", content="hi")
    assert m.tool_calls is None


# ---------- Anthropic wire-format reconstruction ----------


def test_message_to_anthropic_assistant_no_tools_stays_string_content():
    m = LLMMessage(role="assistant", content="all done")
    wire = _message_to_anthropic(m)
    assert wire == {"role": "assistant", "content": "all done"}


def test_message_to_anthropic_assistant_with_tools_emits_content_blocks():
    m = LLMMessage(
        role="assistant",
        content="let me look that up",
        tool_calls=(
            ToolCall(id="c1", name="my_tool", args={"q": "x"}),
        ),
    )
    wire = _message_to_anthropic(m)
    assert wire["role"] == "assistant"
    blocks = wire["content"]
    assert isinstance(blocks, list)
    # text block first, tool_use block second
    assert blocks[0] == {"type": "text", "text": "let me look that up"}
    assert blocks[1] == {
        "type": "tool_use",
        "id": "c1",
        "name": "my_tool",
        "input": {"q": "x"},
    }


def test_message_to_anthropic_assistant_with_empty_text_omits_text_block():
    """Anthropic accepts a tool_use-only assistant message; the text
    block is only emitted when content is non-empty."""
    m = LLMMessage(
        role="assistant",
        content="",
        tool_calls=(
            ToolCall(id="c1", name="my_tool", args={"q": "x"}),
        ),
    )
    wire = _message_to_anthropic(m)
    assert len(wire["content"]) == 1
    assert wire["content"][0]["type"] == "tool_use"


def test_message_to_anthropic_assistant_with_multiple_tool_calls():
    m = LLMMessage(
        role="assistant",
        content="dispatching",
        tool_calls=(
            ToolCall(id="c1", name="a", args={}),
            ToolCall(id="c2", name="b", args={"k": 1}),
        ),
    )
    wire = _message_to_anthropic(m)
    blocks = wire["content"]
    assert [b["type"] for b in blocks] == ["text", "tool_use", "tool_use"]
    assert blocks[1]["id"] == "c1"
    assert blocks[2]["id"] == "c2"


# ---------- Runtime: assistant message carries tool_calls in history ----


class _Out(BaseModel):
    text: str


class _ToolIn(BaseModel):
    q: str


class _ToolOut(BaseModel):
    answer: str


class _CapturingProvider:
    """Provider that records every messages= list it sees, then
    returns canned responses in order. Lets the test assert exactly
    what the runtime forwarded to the provider on each turn."""

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self.calls: list[list[LLMMessage]] = []

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
        # Defensive deep copy via the message's to_dict() so the test
        # observes exactly what the runtime would send, not a list it
        # might mutate further.
        self.calls.append(list(messages))
        return self._responses.pop(0)

    def estimate_cost(self, *, input_tokens, output_tokens, model) -> Decimal:
        return Decimal("0")

    def count_tokens(self, *, system, messages, model) -> int:
        return 100


def _setup_tool_behavior():
    @tool(
        name="my_tool",
        description="t",
        input_schema=_ToolIn,
        output_schema=_ToolOut,
        deterministic=True,
    )
    def my_tool(args, ctx):
        return _ToolOut(answer=f"answer:{args.q}")

    from activegraph.tools.decorators import get_tool_registry

    t = next(t for t in get_tool_registry() if t.name == "my_tool")

    received: list = []

    @behavior(name="seed", on=["goal.created"])
    def seed(event, graph, ctx):
        graph.add_object("doc", {"title": "t"})

    @llm_behavior(
        name="ex",
        on=["object.created"],
        where={"object.type": "doc"},
        output_schema=_Out,
        tools=[t],
    )
    def ex(event, graph, ctx, out):
        received.append(out)

    return received


def _resp(*, parsed=None, tool_calls=None) -> LLMResponse:
    return LLMResponse(
        raw_text="thinking..." if tool_calls else "",
        parsed=parsed,
        input_tokens=10,
        output_tokens=5,
        cost_usd=Decimal("0"),
        latency_seconds=0.1,
        model="claude-sonnet-4-5",
        finish_reason="end_turn" if tool_calls is None else "tool_use",
        tool_calls=tool_calls,
    )


def test_runtime_appends_assistant_message_with_tool_calls():
    """The crux of v1.0.3 #4: when the LLM returns tool_use blocks,
    the next provider call's messages list contains an assistant
    message whose tool_calls field carries the originating ToolCall
    objects. Without this, the wire-format adapter can't reconstruct
    the spec-required tool_use blocks."""

    _setup_tool_behavior()

    provider = _CapturingProvider([
        _resp(tool_calls=[ToolCall(id="c1", name="my_tool", args={"q": "x"})]),
        _resp(parsed=_Out(text="done")),
    ])
    rt = Runtime(Graph(), llm_provider=provider)
    rt.run_goal("g")

    # Two provider calls. The second one's messages must contain the
    # assistant turn with tool_calls populated.
    assert len(provider.calls) == 2
    second_call_messages = provider.calls[1]
    assistant_with_tools = [
        m for m in second_call_messages
        if m.role == "assistant" and m.tool_calls
    ]
    assert len(assistant_with_tools) == 1
    asst = assistant_with_tools[0]
    assert asst.content == "thinking..."
    assert len(asst.tool_calls) == 1
    assert asst.tool_calls[0].id == "c1"
    assert asst.tool_calls[0].name == "my_tool"


def test_wire_format_assistant_message_carries_tool_use_blocks():
    """End-to-end check at the wire shape: every tool_result block in
    a user message has a matching tool_use_id in the preceding
    assistant message's content blocks. The Vertex AI proxy enforces
    this exact invariant; this test guards against the proxy 400."""

    _setup_tool_behavior()

    provider = _CapturingProvider([
        _resp(tool_calls=[ToolCall(id="c1", name="my_tool", args={"q": "x"})]),
        _resp(parsed=_Out(text="done")),
    ])
    rt = Runtime(Graph(), llm_provider=provider)
    rt.run_goal("g")

    # Convert the second call's messages through the Anthropic
    # adapter — the same path the live provider uses.
    wire_msgs = [_message_to_anthropic(m) for m in provider.calls[1]]
    # Walk pairs: every (assistant, user-with-tool_result) needs the
    # tool_use_ids to match.
    for i, msg in enumerate(wire_msgs):
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        tool_result_ids = [
            b["tool_use_id"] for b in content if b.get("type") == "tool_result"
        ]
        if not tool_result_ids:
            continue
        # The previous wire message must be an assistant with matching
        # tool_use blocks.
        prev = wire_msgs[i - 1]
        assert prev["role"] == "assistant"
        prev_content = prev["content"]
        assert isinstance(prev_content, list), (
            "v1.0.3 #4: assistant turn preceding tool_result must carry "
            "content blocks, not string content"
        )
        tool_use_ids = [
            b["id"] for b in prev_content if b.get("type") == "tool_use"
        ]
        for tr_id in tool_result_ids:
            assert tr_id in tool_use_ids, (
                f"tool_result references tool_use_id={tr_id!r} but the "
                f"preceding assistant message has tool_use ids "
                f"{tool_use_ids}"
            )


# ---------- Recorded provider response roundtrip ---------------------------


def test_recorded_provider_roundtrips_tool_calls(tmp_path):
    """The adjacent fix in scope for v1.0.3 #4: a fixture that
    captures a tool-using turn now reconstructs the response's
    tool_calls on replay. Without this, recorded multi-turn
    exchanges are silently lossy — the second turn's prompt hash
    differs from the live one, and the test goes green for the
    wrong reason (no tools dispatched)."""

    fixture = {
        "raw_text": "thinking...",
        "parsed": None,
        "input_tokens": 10,
        "output_tokens": 5,
        "cost_usd": "0.001",
        "latency_seconds": 0.1,
        "model": "claude-sonnet-4-5",
        "finish_reason": "tool_use",
        "seed": None,
        "provider_meta": {},
        "tool_calls": [
            {"id": "c1", "name": "my_tool", "args": {"q": "x"}},
        ],
    }
    from activegraph.llm.recorded import _response_from_fixture

    response = _response_from_fixture(fixture, output_schema=None)
    assert response.tool_calls is not None
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "c1"
    assert response.tool_calls[0].name == "my_tool"
    assert response.tool_calls[0].args == {"q": "x"}


def test_recorded_provider_missing_tool_calls_key_is_none():
    """Pre-v1.0.3 fixtures don't have a tool_calls key; round-trip
    to None, not an empty list — preserves the runtime's
    `getattr(...) or []` branch semantics."""
    fixture = {
        "raw_text": "done",
        "parsed": None,
        "input_tokens": 1,
        "output_tokens": 1,
        "cost_usd": "0",
        "latency_seconds": 0.0,
        "model": "m",
        "finish_reason": "end_turn",
        "seed": None,
        "provider_meta": {},
    }
    from activegraph.llm.recorded import _response_from_fixture

    response = _response_from_fixture(fixture, output_schema=None)
    assert response.tool_calls is None
