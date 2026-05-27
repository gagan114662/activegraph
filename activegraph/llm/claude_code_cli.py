"""Claude Code CLI provider — uses local OAuth subscription, no API key.

This provider subprocess-spawns the `claude` CLI binary (typically at
`~/.local/bin/claude`) with `--print --output-format=stream-json`, parses
the streaming JSON events, and returns an `LLMResponse`. Authentication
uses the operator's local Claude Code subscription (keychain-stored OAuth
token) rather than an `ANTHROPIC_API_KEY`. This is the same dispatch
mechanism the active_graph dark-factory bridge uses for its Pentagon
agents.

Why it exists:
  * Lets activegraph run on an operator's Claude Code MAX subscription
    without provisioning a separate Anthropic API key + billing relation.
  * Aligns the dark factory's runtime authentication with what it
    already uses for agent dispatch (single source of auth).
  * Makes activegraph's `behavior.failed` machinery the canonical
    failure-event store for the dark factory — Codex credit exhaustion,
    Claude 429 session limits, and provider errors all surface as the
    same kind of structured event the rest of the framework consumes.

v1 scope (this file):
  * Single-turn `complete()` — no multi-turn conversation history beyond
    serializing `messages` into one prompt.
  * No tools — raises `NotImplementedError` if the runtime passes a
    `tools=` list. Tool support requires MCP wiring (v2).
  * No streaming response — collects the full stream-json output then
    returns one `LLMResponse`. Matches the v0.6 Protocol's
    "no streaming" decision.

Compared to AnthropicProvider:
  * Same Protocol shape (see `activegraph/llm/provider.py`).
  * Same error mapping rules: 429 → `llm.rate_limited`, network/timeout
    → `llm.network_error` (see `_classify_claude_error`).
  * `count_tokens()` is a heuristic (chars/4) rather than the
    Anthropic-official `count_tokens` API, because the CLI doesn't
    expose that endpoint. Budget pre-gating is therefore approximate
    for this provider; the real `cost_usd` comes from the CLI's
    own `total_cost_usd` field in the stream-json result event.

The CLI is invoked with `CLAUDECODE` and related env vars scrubbed,
matching how Pentagon's `ClaudeLaunchBuilder` invokes it (preserves
auth across nested Claude Code session boundaries).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from decimal import Decimal
from typing import Any, Optional

from activegraph.llm.errors import LLMBehaviorError
from activegraph.llm.types import LLMMessage, LLMResponse

# Pricing for claude-opus-4-7 per Anthropic public documentation. Used by
# estimate_cost() for pre-call budget gating; the actual cost returned by
# the CLI's `total_cost_usd` field is authoritative post-call.
_DEFAULT_PRICING: dict[str, dict[str, str]] = {
    "claude-opus-4-7": {"input": "15", "output": "75"},
    "claude-opus-4": {"input": "15", "output": "75"},
    "claude-sonnet-4-6": {"input": "3", "output": "15"},
    "claude-sonnet-4-5": {"input": "3", "output": "15"},
    "claude-sonnet-4": {"input": "3", "output": "15"},
    "claude-haiku-4-5": {"input": "1", "output": "5"},
}

# Env vars that, if inherited from a parent Claude Code session, cause
# the spawned `claude` CLI to misbehave (rejected auth, refusal to start
# interactive features). Scrubbed before exec, matching Pentagon's
# ClaudeLaunchBuilder pattern.
_STRIP_ENV_VARS = (
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_EXECPATH",
    "AI_AGENT",
)

_DEFAULT_CLI_PATH = os.path.expanduser("~/.local/bin/claude")


def _pricing_for(model: str, pricing: dict[str, dict[str, str]]) -> tuple[Decimal, Decimal]:
    entry = pricing.get(model)
    if entry is None:
        # Permissive fallback: assume sonnet pricing for unknown claude-* names.
        # Matches AnthropicProvider's behavior.
        if model.startswith("claude-sonnet"):
            entry = pricing.get("claude-sonnet-4")
        elif model.startswith("claude-opus"):
            entry = pricing.get("claude-opus-4")
        elif model.startswith("claude-haiku"):
            entry = pricing.get("claude-haiku-4-5")
        else:
            entry = {"input": "15", "output": "75"}
    return Decimal(str(entry["input"])), Decimal(str(entry["output"]))


class ClaudeCodeCliProvider:
    """LLMProvider that dispatches via the local `claude` CLI."""

    default_model: str = "claude-opus-4-7"
    runtime_parses_output: bool = True

    def __init__(
        self,
        *,
        cli_path: Optional[str] = None,
        mcp_config: Optional[dict[str, Any]] = None,
        pricing: Optional[dict[str, dict[str, str]]] = None,
        env_overrides: Optional[dict[str, str]] = None,
    ) -> None:
        self._cli_path = cli_path or os.environ.get("CLAUDE_CLI", _DEFAULT_CLI_PATH)
        self._mcp_config = mcp_config
        self._pricing: dict[str, dict[str, str]] = dict(pricing or _DEFAULT_PRICING)
        self._env_overrides = env_overrides or {}

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
        if tools:
            raise NotImplementedError(
                "ClaudeCodeCliProvider v1 does not support tools. "
                "Tool use requires wiring activegraph's tools through "
                "claude's --mcp-config; deferred to v2."
            )

        prompt = self._serialize_prompt(system, messages, output_schema)
        args = self._build_args(model)
        env = self._build_env()

        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                [self._cli_path, *args],
                input=prompt,
                capture_output=True,
                text=True,
                env=env,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise LLMBehaviorError(
                "llm.network_error",
                f"claude CLI timed out after {timeout_seconds}s",
                payload_extras={
                    "model": model,
                    "exception_type": "TimeoutExpired",
                    "message": str(e),
                    "timeout_seconds": float(timeout_seconds),
                },
            ) from e
        except FileNotFoundError as e:
            raise LLMBehaviorError(
                "llm.network_error",
                f"claude CLI not found at {self._cli_path}",
                payload_extras={
                    "model": model,
                    "exception_type": "FileNotFoundError",
                    "message": str(e),
                    "cli_path": self._cli_path,
                },
            ) from e
        latency = time.monotonic() - t0

        result_event = self._parse_stream_json(proc.stdout)
        if result_event is None:
            raise LLMBehaviorError(
                "llm.network_error",
                "claude CLI produced no result event",
                payload_extras={
                    "model": model,
                    "exception_type": "MissingResultEvent",
                    "message": (proc.stderr or proc.stdout)[-2000:],
                    "exit_code": proc.returncode,
                },
            )

        if result_event.get("is_error"):
            reason = _classify_claude_error(result_event)
            extras: dict[str, Any] = {
                "model": model,
                "exception_type": "ClaudeCliError",
                "message": str(result_event.get("result") or "claude returned is_error"),
                "api_error_status": result_event.get("api_error_status"),
                "duration_ms": result_event.get("duration_ms"),
                "session_id": result_event.get("session_id"),
            }
            raise LLMBehaviorError(reason, extras["message"], payload_extras=extras)

        text = self._extract_text(result_event, proc.stdout)
        usage = result_event.get("usage") or {}
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        actual_cost_str = result_event.get("total_cost_usd")
        cost = (
            Decimal(str(actual_cost_str))
            if actual_cost_str is not None
            else self.estimate_cost(
                input_tokens=input_tokens, output_tokens=output_tokens, model=model
            )
        )

        return LLMResponse(
            raw_text=text,
            parsed=None,  # runtime_parses_output handles schema parsing
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_seconds=latency,
            model=model,
            finish_reason=str(result_event.get("stop_reason") or "end_turn"),
            cache_hit=False,
            provider_meta={
                "session_id": result_event.get("session_id"),
                "duration_ms": result_event.get("duration_ms"),
                "duration_api_ms": result_event.get("duration_api_ms"),
                "cache_creation_input_tokens": int(
                    usage.get("cache_creation_input_tokens") or 0
                ),
                "cache_read_input_tokens": int(
                    usage.get("cache_read_input_tokens") or 0
                ),
            },
        )

    def estimate_cost(
        self, *, input_tokens: int, output_tokens: int, model: str
    ) -> Decimal:
        in_rate, out_rate = _pricing_for(model, self._pricing)
        return (
            in_rate * Decimal(input_tokens) + out_rate * Decimal(output_tokens)
        ) / Decimal("1000000")

    def count_tokens(
        self, *, system: str, messages: list[LLMMessage], model: str
    ) -> int:
        # Heuristic: ~4 characters per token. Accurate enough for budget
        # pre-gating. Real token count comes back in the LLMResponse.
        text = system + "".join(m.content for m in messages)
        return max(1, len(text) // 4)

    def recognizes_model(self, name: str) -> bool:
        return name.startswith("claude-")

    # ---- internals --------------------------------------------------------

    def _serialize_prompt(
        self,
        system: str,
        messages: list[LLMMessage],
        output_schema: Optional[type],
    ) -> str:
        """Flatten activegraph's (system, messages) into a single prompt.

        claude `-p` mode takes one prompt argument or stdin input. We
        prepend the system prompt as a labeled section, then render each
        message with its role.
        """
        parts: list[str] = []
        if system:
            parts.append("[SYSTEM]\n" + system)
        for m in messages:
            parts.append(f"[{m.role.upper()}]\n{m.content}")
        if output_schema is not None:
            schema_name = getattr(output_schema, "__name__", "OutputSchema")
            parts.append(
                f"[OUTPUT-INSTRUCTION]\nReturn ONLY a JSON object matching the {schema_name} schema. "
                "No prose, no markdown, no fences."
            )
        return "\n\n".join(parts)

    def _build_args(self, model: str) -> list[str]:
        args = [
            "--print",
            "--output-format", "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
            "--model", model,
        ]
        if self._mcp_config is not None:
            args.extend(["--strict-mcp-config", "--mcp-config", json.dumps(self._mcp_config)])
        return args

    def _build_env(self) -> dict[str, str]:
        env = dict(os.environ)
        for key in _STRIP_ENV_VARS:
            env.pop(key, None)
        env.update(self._env_overrides)
        return env

    @staticmethod
    def _parse_stream_json(stdout: str) -> Optional[dict[str, Any]]:
        """Walk the stream-json line by line, return the final result event.

        claude `-p --output-format=stream-json` emits one JSON object per
        line. We collect the last event with `type == "result"` which
        carries the final response + token counts + cost.
        """
        result_event: Optional[dict[str, Any]] = None
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "result":
                result_event = event
        return result_event

    @staticmethod
    def _extract_text(result_event: dict[str, Any], stdout: str) -> str:
        """Prefer the result event's `result` field; fall back to the
        last assistant message's text content if missing.
        """
        if isinstance(result_event.get("result"), str):
            return result_event["result"]
        # Fall back to walking assistant events.
        last_text: Optional[str] = None
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "assistant":
                content = (event.get("message") or {}).get("content") or []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        last_text = block.get("text", last_text)
        return last_text or ""


def _classify_claude_error(result_event: dict[str, Any]) -> str:
    """Map a claude-CLI is_error result to an activegraph reason code.

    Reason codes match `_classify_provider_exception` in anthropic.py so
    downstream consumers can treat both providers uniformly.
    """
    status = result_event.get("api_error_status")
    if status == 429:
        return "llm.rate_limited"
    if status in {408, 504}:
        return "llm.network_error"
    text = str(result_event.get("result") or "").lower()
    if "session limit" in text or "rate limit" in text or "usage limit" in text:
        return "llm.rate_limited"
    if "authentication" in text or "unauthorized" in text or "credential" in text:
        # Auth failures: use network_error rather than inventing a new
        # reason code that the runtime doesn't recognize. Operator should
        # treat the message text as the actionable signal.
        return "llm.network_error"
    return "llm.network_error"
