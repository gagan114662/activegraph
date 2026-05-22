"""T4 failing tests for OpenAI tool-shape translation.

Frame: ``t4-openai-tool-shape-translation``.
Spec inputs:
- D-1 amendment ``inner:7ae37da``.
- D-3 amendment ``inner:2f82f19``.
- Sasha second-pass ``inner:12f71bf``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from activegraph import LLMBehaviorError, Tool
from activegraph.llm import AnthropicProvider, LLMMessage, OpenAIProvider, ToolCall


class _LookupArgs(BaseModel):
    query: str


def _tool_definition() -> dict:
    tool = Tool(
        name="lookup_fact",
        fn=lambda args, ctx: {"answer": args.query},
        description="Look up a fact.",
        input_schema=_LookupArgs,
    )
    return tool.to_definition()


def _openai_raw_with_tool_call() -> SimpleNamespace:
    return SimpleNamespace(
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
                                arguments='{"query":"alpha"}',
                            ),
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3),
        model="gpt-4o-mini",
    )


def _openai_raw_final() -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content='{"answer":"alpha fact"}'),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=9, completion_tokens=4),
        model="gpt-4o-mini",
    )


def test_tool_definition_stays_internal_and_anthropic_receives_it_unchanged() -> None:
    tool_def = _tool_definition()
    assert set(tool_def) == {"name", "description", "input_schema"}
    assert tool_def["name"] == "lookup_fact"
    assert "type" not in tool_def
    assert "function" not in tool_def

    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text='{"answer":"ok"}')],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        model="claude-sonnet-4-5",
        stop_reason="end_turn",
    )
    AnthropicProvider(client=client).complete(
        system="sys",
        messages=[LLMMessage(role="user", content="go")],
        model="claude-sonnet-4-5",
        max_tokens=32,
        temperature=0.0,
        top_p=1.0,
        output_schema=None,
        timeout_seconds=30,
        tools=[tool_def],
    )

    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["tools"] == [tool_def]


def test_openai_translates_internal_tools_to_function_shape_and_extracts_calls() -> None:
    client = MagicMock()
    client.chat.completions.create.return_value = _openai_raw_with_tool_call()

    response = OpenAIProvider(client=client).complete(
        system="sys",
        messages=[LLMMessage(role="user", content="go")],
        model="gpt-4o-mini",
        max_tokens=32,
        temperature=0.0,
        top_p=1.0,
        output_schema=None,
        timeout_seconds=30,
        tools=[_tool_definition()],
    )

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "lookup_fact",
                "description": "Look up a fact.",
                "parameters": _tool_definition()["input_schema"],
            },
        }
    ]
    assert response.finish_reason == "tool_calls"
    assert response.tool_calls == [
        ToolCall(id="call_1", name="lookup_fact", args={"query": "alpha"})
    ]
    assert response.parsed is None


def test_openai_second_turn_echoes_assistant_tool_calls_and_tool_result() -> None:
    client = MagicMock()
    client.chat.completions.create.return_value = _openai_raw_final()
    call = ToolCall(id="call_1", name="lookup_fact", args={"query": "alpha"})

    OpenAIProvider(client=client).complete(
        system="sys",
        messages=[
            LLMMessage(role="user", content="go"),
            LLMMessage(role="assistant", content="", tool_calls=(call,)),
            LLMMessage(
                role="tool",
                content='{"answer":"alpha fact"}',
                tool_use_id="call_1",
                tool_name="lookup_fact",
            ),
        ],
        model="gpt-4o-mini",
        max_tokens=32,
        temperature=0.0,
        top_p=1.0,
        output_schema=None,
        timeout_seconds=30,
        tools=[_tool_definition()],
    )

    sent = client.chat.completions.create.call_args.kwargs["messages"]
    assistant = sent[-2]
    tool_result = sent[-1]
    assert assistant["role"] == "assistant"
    assert assistant["tool_calls"] == [
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "lookup_fact",
                "arguments": '{"query":"alpha"}',
            },
        }
    ]
    assert tool_result == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": '{"answer":"alpha fact"}',
    }


@pytest.mark.parametrize(
    "bad_tool",
    [
        {"description": "missing name", "input_schema": {"type": "object"}},
        {"name": "", "input_schema": {"type": "object"}},
        {"name": "x", "description": 3, "input_schema": {"type": "object"}},
        {"name": "x", "input_schema": ["not", "a", "mapping"]},
    ],
)
def test_openai_malformed_direct_tool_dicts_fail_pre_sdk(bad_tool: dict) -> None:
    client = MagicMock()

    with pytest.raises(LLMBehaviorError) as exc:
        OpenAIProvider(client=client).complete(
            system="sys",
            messages=[LLMMessage(role="user", content="go")],
            model="gpt-4o-mini",
            max_tokens=32,
            temperature=0.0,
            top_p=1.0,
            output_schema=None,
            timeout_seconds=30,
            tools=[bad_tool],
        )

    assert exc.value.reason == "llm.prompt_assembly_error"
    client.chat.completions.create.assert_not_called()
