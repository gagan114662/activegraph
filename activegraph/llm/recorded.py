"""Fixture-based LLM providers for tests.

CONTRACT v0.6 #12, plus decision-3 adjustment for `recorded_at`:

  RecordedLLMProvider   — looks up fixtures by prompt hash. Tests run
                          against this. Raises if a fixture is
                          missing (so tests fail loud rather than
                          regressing into live calls).

  RecordingLLMProvider  — wraps another provider, mirrors every call
                          to disk as a fixture file. Use once with
                          `--record` to seed fixtures, then commit
                          them. Marked with `@pytest.mark.records_llm`
                          so they don't run in CI without explicit
                          opt-in.

Fixture file layout (`tests/fixtures/llm/<sha256_hex>.json`):

    {
      "prompt_hash": "<sha256_hex>",
      "recorded_at": "2026-05-15T10:32:01Z",   # outside the hash
      "model":       "claude-sonnet-4-5",
      "prompt": {                              # only this hashes
        "model": ..., "system": ..., "messages": [...],
        "output_schema_name": ..., "output_schema_json": {...},
        "max_tokens": ..., "temperature": ..., "top_p": ...,
        "deterministic": ...
      },
      "response": {
        "raw_text": "...", "parsed": {...},
        "input_tokens": 0, "output_tokens": 0,
        "cost_usd": "0.001", "latency_seconds": 0.0,
        "model": "...", "finish_reason": "end_turn",
        "seed": null, "provider_meta": {}
      }
    }

`recorded_at` is intentionally OUTSIDE the hashed `prompt` payload so
it doesn't perturb lookups but stays available for future debugging
when fixtures drift.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from activegraph.llm.errors import LLMBehaviorError
from activegraph.llm.provider import LLMProvider
from activegraph.llm.types import LLMMessage, LLMResponse


def _now_iso() -> str:
    return (
        datetime.now(tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _canonical_prompt_payload(
    *,
    model: str,
    system: str,
    messages: list[LLMMessage],
    output_schema: Optional[type],
    max_tokens: int,
    temperature: float,
    top_p: float,
    deterministic: bool,
    tools: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    from activegraph.llm.prompt import schema_to_json

    return {
        "model": model,
        "system": system,
        "messages": [m.to_dict() for m in messages],
        "output_schema_name": (
            getattr(output_schema, "__name__", None) if output_schema else None
        ),
        "output_schema_json": schema_to_json(output_schema),
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
        "top_p": float(top_p),
        "deterministic": bool(deterministic),
        # v0.7: tool definitions contribute to the prompt hash so a
        # behavior gaining or losing a tool produces a different key.
        "tools": list(tools) if tools else None,
    }


def _hash_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------- RecordedLLMProvider ---------------------------------------------


class RecordedLLMProvider(LLMProvider):
    """Reads fixtures from a directory keyed by prompt hash.

    Tests construct one of these instead of an `AnthropicProvider`.
    Missing fixtures raise so the test fails loud — there is no
    silent fallthrough to a real call.
    """

    def __init__(self, fixtures_dir: str) -> None:
        self._dir = fixtures_dir

    # ---- LLMProvider methods ----

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
        payload = _canonical_prompt_payload(
            model=model,
            system=system,
            messages=messages,
            output_schema=output_schema,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            deterministic=(temperature == 0.0 and top_p == 1.0),
            tools=tools,
        )
        prompt_hash = _hash_payload(payload)
        path = os.path.join(self._dir, f"{prompt_hash}.json")
        if not os.path.exists(path):
            raise LLMBehaviorError(
                "llm.fixture_missing",
                f"no recorded fixture for prompt_hash={prompt_hash} in {self._dir}",
                payload_extras={"prompt_hash": prompt_hash, "fixtures_dir": self._dir},
            )
        with open(path, "r") as f:
            data = json.load(f)
        return _response_from_fixture(data["response"], output_schema)

    def estimate_cost(
        self, *, input_tokens: int, output_tokens: int, model: str
    ) -> Decimal:
        # Tests don't care about real pricing; just return zero.
        return Decimal("0")

    def count_tokens(
        self, *, system: str, messages: list[LLMMessage], model: str
    ) -> int:
        total = len(system) + sum(len(m.content) for m in messages)
        return max(1, total // 4)


def _response_from_fixture(
    rdata: dict[str, Any], output_schema: Optional[type]
) -> LLMResponse:
    parsed_raw = rdata.get("parsed")
    parsed: Any = None
    if parsed_raw is not None and output_schema is not None:
        parsed = output_schema.model_validate(parsed_raw)
    elif parsed_raw is not None:
        parsed = parsed_raw
    cost = rdata.get("cost_usd", "0")
    if not isinstance(cost, Decimal):
        cost = Decimal(str(cost))
    return LLMResponse(
        raw_text=rdata.get("raw_text", ""),
        parsed=parsed,
        input_tokens=int(rdata.get("input_tokens", 0) or 0),
        output_tokens=int(rdata.get("output_tokens", 0) or 0),
        cost_usd=cost,
        latency_seconds=float(rdata.get("latency_seconds", 0.0) or 0.0),
        model=rdata.get("model", "?"),
        finish_reason=rdata.get("finish_reason", "end_turn"),
        seed=rdata.get("seed"),
        cache_hit=False,
        provider_meta=dict(rdata.get("provider_meta", {}) or {}),
    )


# ---------- RecordingLLMProvider --------------------------------------------


class RecordingLLMProvider(LLMProvider):
    """Wraps a real provider and persists responses to fixtures.

    Use this once (with `--record` opt-in) to seed `tests/fixtures/llm`
    against the live Anthropic API, then commit the fixtures and run
    tests against `RecordedLLMProvider` thereafter.
    """

    def __init__(self, inner: LLMProvider, fixtures_dir: str) -> None:
        self._inner = inner
        self._dir = fixtures_dir
        os.makedirs(self._dir, exist_ok=True)

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
        response = self._inner.complete(
            system=system,
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
            tools=tools,
        )
        payload = _canonical_prompt_payload(
            model=model,
            system=system,
            messages=messages,
            output_schema=output_schema,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            deterministic=(temperature == 0.0 and top_p == 1.0),
            tools=tools,
        )
        prompt_hash = _hash_payload(payload)
        fixture = {
            "prompt_hash": prompt_hash,
            "recorded_at": _now_iso(),
            "model": model,
            "prompt": payload,
            "response": response.to_dict(),
        }
        path = os.path.join(self._dir, f"{prompt_hash}.json")
        with open(path, "w") as f:
            json.dump(fixture, f, indent=2, sort_keys=True)
        return response

    def estimate_cost(
        self, *, input_tokens: int, output_tokens: int, model: str
    ) -> Decimal:
        return self._inner.estimate_cost(
            input_tokens=input_tokens, output_tokens=output_tokens, model=model
        )

    def count_tokens(
        self, *, system: str, messages: list[LLMMessage], model: str
    ) -> int:
        return self._inner.count_tokens(
            system=system, messages=messages, model=model
        )
