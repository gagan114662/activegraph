"""OpenAIProvider unit tests with a mocked SDK client.

CONTRACT v1.0.1 #5 / CONTRACT v0.6 #11: exception mapping (network vs
rate-limit), no-API-key handling, structured-output extraction
through the shared `parse_structured_response` path, family-prefix
pricing lookup, tool-shape translation, count_tokens fallback.

Mirrors `tests/test_llm_anthropic.py`. Same fake-client shape; the
only intentional divergences are the OpenAI response structure
(`choices[0].message.content`, `usage.prompt_tokens`) and the tool-
shape translation boundary.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from activegraph.llm import (
    LLMBehaviorError,
    LLMMessage,
    OpenAIProvider,
    ToolCall,
)


class _Out(BaseModel):
    n: int


def _client_returning(text: str, *, in_tok: int = 10, out_tok: int = 5):
    raw = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=in_tok, completion_tokens=out_tok),
        model="gpt-4o-mini",
    )
    client = MagicMock()
    client.chat.completions.create.return_value = raw
    return client


def test_complete_parses_structured_output():
    client = _client_returning('{"n": 42}')
    p = OpenAIProvider(client=client)
    r = p.complete(
        system="sys",
        messages=[LLMMessage(role="user", content="u")],
        model="gpt-4o-mini",
        max_tokens=64,
        temperature=0.0,
        top_p=1.0,
        output_schema=_Out,
        timeout_seconds=30,
    )
    assert isinstance(r.parsed, _Out)
    assert r.parsed.n == 42
    assert r.input_tokens == 10
    assert r.output_tokens == 5
    assert r.finish_reason == "stop"
    assert r.seed is None


def test_complete_extracts_json_from_fenced_block():
    client = _client_returning('Here:\n```json\n{"n": 9}\n```\nDone.')
    p = OpenAIProvider(client=client)
    r = p.complete(
        system="",
        messages=[LLMMessage(role="user", content="u")],
        model="gpt-4o-mini",
        max_tokens=64,
        temperature=0.0,
        top_p=1.0,
        output_schema=_Out,
        timeout_seconds=30,
    )
    assert r.parsed.n == 9


def test_complete_raises_parse_error_when_no_json():
    client = _client_returning("just prose, no json at all")
    p = OpenAIProvider(client=client)
    with pytest.raises(LLMBehaviorError) as exc:
        p.complete(
            system="",
            messages=[LLMMessage(role="user", content="u")],
            model="gpt-4o-mini",
            max_tokens=64,
            temperature=0.0,
            top_p=1.0,
            output_schema=_Out,
            timeout_seconds=30,
        )
    assert exc.value.reason == "llm.parse_error"


def test_complete_raises_schema_violation_when_wrong_shape():
    client = _client_returning('{"oops": 1}')
    p = OpenAIProvider(client=client)
    with pytest.raises(LLMBehaviorError) as exc:
        p.complete(
            system="",
            messages=[LLMMessage(role="user", content="u")],
            model="gpt-4o-mini",
            max_tokens=64,
            temperature=0.0,
            top_p=1.0,
            output_schema=_Out,
            timeout_seconds=30,
        )
    assert exc.value.reason == "llm.schema_violation"


def test_complete_maps_network_exception():
    client = MagicMock()
    client.chat.completions.create.side_effect = TimeoutError("connect timeout")
    p = OpenAIProvider(client=client)
    with pytest.raises(LLMBehaviorError) as exc:
        p.complete(
            system="",
            messages=[LLMMessage(role="user", content="u")],
            model="gpt-4o-mini",
            max_tokens=64,
            temperature=0.0,
            top_p=1.0,
            output_schema=None,
            timeout_seconds=30,
        )
    assert exc.value.reason == "llm.network_error"


def test_complete_maps_rate_limit_exception():
    class RateLimitError(Exception):
        pass

    client = MagicMock()
    client.chat.completions.create.side_effect = RateLimitError("429 too many")
    p = OpenAIProvider(client=client)
    with pytest.raises(LLMBehaviorError) as exc:
        p.complete(
            system="",
            messages=[LLMMessage(role="user", content="u")],
            model="gpt-4o-mini",
            max_tokens=64,
            temperature=0.0,
            top_p=1.0,
            output_schema=None,
            timeout_seconds=30,
        )
    assert exc.value.reason == "llm.rate_limited"


def test_complete_maps_auth_failure_to_network_error():
    # CONTRACT v1.0.1 #5: closed reason taxonomy; auth failures land
    # in llm.network_error with the message preserved verbatim.
    class AuthenticationError(Exception):
        pass

    client = MagicMock()
    client.chat.completions.create.side_effect = AuthenticationError(
        "Invalid API key provided"
    )
    p = OpenAIProvider(client=client)
    with pytest.raises(LLMBehaviorError) as exc:
        p.complete(
            system="",
            messages=[LLMMessage(role="user", content="u")],
            model="gpt-4o-mini",
            max_tokens=64,
            temperature=0.0,
            top_p=1.0,
            output_schema=None,
            timeout_seconds=30,
        )
    assert exc.value.reason == "llm.network_error"
    assert "Invalid API key" in str(exc.value)


def test_complete_translates_tools_to_openai_function_shape():
    # CONTRACT v1.1 B-1 / T4: the Protocol still accepts framework
    # tool definitions; OpenAIProvider translates at the provider edge.
    client = _client_returning('{"n": 1}')
    p = OpenAIProvider(client=client)
    response = p.complete(
        system="",
        messages=[LLMMessage(role="user", content="u")],
        model="gpt-4o-mini",
        max_tokens=64,
        temperature=0.0,
        top_p=1.0,
        output_schema=None,
        timeout_seconds=30,
        tools=[{"name": "foo", "description": "d", "input_schema": {}}],
    )

    assert response.raw_text == '{"n": 1}'
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "foo",
                "description": "d",
                "parameters": {},
            },
        }
    ]


def test_estimate_cost_uses_family_prefix():
    p = OpenAIProvider(client=MagicMock())
    mini = p.estimate_cost(
        input_tokens=1_000_000, output_tokens=0, model="gpt-4o-mini-2024-07-18"
    )
    base = p.estimate_cost(
        input_tokens=1_000_000, output_tokens=0, model="gpt-4o-2024-11-20"
    )
    turbo = p.estimate_cost(
        input_tokens=1_000_000, output_tokens=0, model="gpt-4-turbo-preview"
    )
    assert mini == Decimal("0.15")
    assert base == Decimal("2.5")
    assert turbo == Decimal("10")


def test_count_tokens_heuristic_fallback_when_tiktoken_missing(monkeypatch):
    # Force the tiktoken import to fail and verify the char/4 heuristic.
    import builtins

    real_import = builtins.__import__

    def fail_tiktoken(name, *args, **kwargs):
        if name == "tiktoken":
            raise ImportError("tiktoken not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_tiktoken)
    p = OpenAIProvider(client=MagicMock())
    n = p.count_tokens(
        system="0123",  # 4 chars
        messages=[LLMMessage(role="user", content="01234567")],  # 8 chars
        model="gpt-4o-mini",
    )
    # (4 + 8) // 4 = 3
    assert n == 3


def test_count_tokens_heuristic_includes_assistant_tool_calls(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fail_tiktoken(name, *args, **kwargs):
        if name == "tiktoken":
            raise ImportError("tiktoken not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_tiktoken)
    p = OpenAIProvider(client=MagicMock())
    n = p.count_tokens(
        system="",
        messages=[
            LLMMessage(
                role="assistant",
                content="",
                tool_calls=(
                    ToolCall(
                        id="call_1",
                        name="lookup_fact",
                        args={"query": "alpha"},
                    ),
                ),
            ),
            LLMMessage(role="tool", content="{}", tool_use_id="call_1"),
        ],
        model="gpt-4o-mini",
    )

    assert n > 1


def test_missing_api_key_raises_when_constructing_real_client(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    p = OpenAIProvider()  # no client override
    # The error message must name OPENAI_API_KEY so the operator
    # knows which env var to set.
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        p.complete(
            system="",
            messages=[LLMMessage(role="user", content="u")],
            model="gpt-4o-mini",
            max_tokens=64,
            temperature=0.0,
            top_p=1.0,
            output_schema=None,
            timeout_seconds=30,
        )
