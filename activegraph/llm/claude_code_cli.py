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
import sys
import time
from decimal import Decimal
from typing import Any, Optional

from activegraph.llm.errors import LLMBehaviorError
from activegraph.llm.types import LLMMessage, LLMResponse


def _try_emit_factory_event(**kwargs: Any) -> None:
    """Best-effort emit to the dark-factory event log.

    Imports lazily so activegraph remains usable without the operator-side
    scripts/ directory on sys.path. Any failure here is swallowed —
    raising would mask the real LLMBehaviorError the caller wants to see.
    """
    try:
        # Look for scripts/factory_events.py up the tree from this file.
        here = os.path.dirname(os.path.abspath(__file__))
        for parent in (here, *list(_walk_parents(here, max_levels=6))):
            scripts_dir = os.path.join(parent, "scripts")
            if os.path.isdir(scripts_dir) and os.path.isfile(os.path.join(scripts_dir, "factory_events.py")):
                if scripts_dir not in sys.path:
                    sys.path.insert(0, scripts_dir)
                break
        import factory_events  # type: ignore

        factory_events.emit_factory_event(**kwargs)
    except Exception as exc:  # noqa: BLE001
        # We never want event-logging to break the LLM call, but a silently
        # broken event pipeline is exactly what the log exists to catch (H13),
        # so surface it on stderr without re-raising.
        try:
            sys.stderr.write(f"[claude_code_cli] factory event emission failed: {exc}\n")
            sys.stderr.flush()
        except Exception:
            pass


def _walk_parents(path: str, max_levels: int) -> Any:
    for _ in range(max_levels):
        parent = os.path.dirname(path)
        if parent == path:
            return
        yield parent
        path = parent

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
        # v2 (#27): when tools are passed, spin up an in-process MCP HTTP
        # server that serves them. claude calls our server via MCP for
        # each tool_use; the server invokes the Python callable
        # in-process and returns the result. After claude finishes, we
        # shut down the server. Tool invocation records land in
        # provider_meta for audit.
        tool_server_ctx = None
        merged_mcp_config = self._mcp_config
        if tools:
            tool_callables = _extract_tool_callables(tools)
            if tool_callables:
                from activegraph.llm._mcp_tool_server import start_tool_server
                tool_server_ctx = start_tool_server(tool_callables)
                # Merge the activegraph tools server into the operator's
                # mcp_config (if any). Don't clobber operator-provided
                # servers like Pentagon's.
                merged_mcp_config = dict(self._mcp_config or {})
                servers = dict(merged_mcp_config.get("mcpServers", {}))
                servers["activegraph"] = {"type": "http", "url": tool_server_ctx.url}
                merged_mcp_config["mcpServers"] = servers
            else:
                # tools= was a list of dict-shaped definitions WITHOUT
                # callable references (e.g. AnthropicProvider's
                # serialized form). We can't invoke them in-process —
                # raise so the runtime falls back to a different provider
                # or the caller passes activegraph Tool objects directly.
                raise NotImplementedError(
                    "ClaudeCodeCliProvider needs activegraph Tool objects "
                    "(with .function callable) for v2 MCP tool support. "
                    "Plain dict tool definitions cannot be invoked in "
                    "this process — pass the Tool objects from the "
                    "runtime instead."
                )

        prompt = self._serialize_prompt(system, messages, output_schema)
        args = self._build_args(model, mcp_config_override=merged_mcp_config)
        env = self._build_env()

        response = None
        try:
            response = self._dispatch(prompt, args, env, timeout_seconds, model, usage_extras={"tool_invocations": []})
        finally:
            if tool_server_ctx is not None:
                try:
                    if response is not None and getattr(response, "provider_meta", None) is not None:
                        response.provider_meta["tool_invocations"] = list(tool_server_ctx.invocations)
                except Exception:
                    pass
                tool_server_ctx.shutdown()
        return response

    def _dispatch(
        self,
        prompt: str,
        args: list[str],
        env: dict[str, str],
        timeout_seconds: float,
        model: str,
        usage_extras: Optional[dict[str, Any]] = None,
    ) -> LLMResponse:
        """Inner dispatch — actually invokes claude. Split from complete() so
        the tool-server lifecycle (start_tool_server / shutdown) wraps the
        whole subprocess + parse + emit flow cleanly.
        """
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
            _try_emit_factory_event(
                type="behavior.failed",
                behavior="activegraph.ClaudeCodeCliProvider",
                reason="llm.network_error",
                message=f"claude CLI timed out after {timeout_seconds}s",
                extras={
                    "model": model,
                    "exception_type": "TimeoutExpired",
                    "timeout_seconds": float(timeout_seconds),
                },
            )
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
            _try_emit_factory_event(
                type="behavior.failed",
                behavior="activegraph.ClaudeCodeCliProvider",
                reason="llm.network_error",
                message=f"claude CLI not found at {self._cli_path}",
                extras={
                    "model": model,
                    "exception_type": "FileNotFoundError",
                    "cli_path": self._cli_path,
                },
            )
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
            _try_emit_factory_event(
                type="behavior.failed",
                behavior="activegraph.ClaudeCodeCliProvider",
                reason="llm.network_error",
                message="claude CLI produced no result event",
                extras={
                    "model": model,
                    "exception_type": "MissingResultEvent",
                    "exit_code": proc.returncode,
                    "stderr_tail": (proc.stderr or proc.stdout)[-500:],
                },
            )
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
            _try_emit_factory_event(
                type="behavior.failed",
                behavior="activegraph.ClaudeCodeCliProvider",
                reason=reason,
                message=extras["message"],
                extras={
                    "model": model,
                    "api_error_status": result_event.get("api_error_status"),
                    "duration_ms": result_event.get("duration_ms"),
                    "session_id": result_event.get("session_id"),
                },
            )
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

        # Skip the emit when an outer layer (Node bridge) will re-emit this
        # event with full Pentagon context. Without this guard, the same
        # dispatch produces three llm.responded rows at three behavior
        # labels and downstream cost aggregators (Blake's caps,
        # factory-health dashboard) triple-count the spend. The bridge
        # sets FACTORY_SUPPRESS_LLM_RESPONDED_EMIT=1 when spawning this
        # provider via bridge_dispatch.py. Standalone library usage
        # (no bridge in the call stack) leaves the env var unset and
        # this emit fires normally.
        if not os.environ.get("FACTORY_SUPPRESS_LLM_RESPONDED_EMIT"):
            _try_emit_factory_event(
                type="llm.responded",
                behavior="activegraph.ClaudeCodeCliProvider",
                extras={
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": float(cost),
                    "latency_seconds": latency,
                    "finish_reason": str(result_event.get("stop_reason") or "end_turn"),
                    "session_id": result_event.get("session_id"),
                    "cache_read_input_tokens": int(usage.get("cache_read_input_tokens") or 0),
                    "cache_creation_input_tokens": int(usage.get("cache_creation_input_tokens") or 0),
                },
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

    def _build_args(self, model: str, mcp_config_override: Optional[dict[str, Any]] = None) -> list[str]:
        args = [
            "--print",
            "--output-format", "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
            "--model", model,
        ]
        effective_mcp = mcp_config_override if mcp_config_override is not None else self._mcp_config
        if effective_mcp is not None:
            args.extend(["--strict-mcp-config", "--mcp-config", json.dumps(effective_mcp)])
        return args

    def _build_env(self) -> dict[str, str]:
        env = dict(os.environ)
        for key in _STRIP_ENV_VARS:
            env.pop(key, None)
        env.update(self._env_overrides)
        # Opus 4.8 multi-turn thinking-preservation mitigation (2026-05-28).
        # On agentic multi-turn tool use (Maya: read -> pytest -> commit, many
        # turns), the claude CLI mangles a `thinking`/`redacted_thinking` block
        # from an earlier assistant turn when it sends the follow-up, and the API
        # rejects the whole request: "400 ... thinking blocks ... must remain as
        # they were in the original response." This 400-failed EVERY T7 gauntlet
        # dispatch (fast claim+complete, no output = looked like ghost_completion).
        # Single-turn dispatches (T6 reviews) never hit it. Disabling extended
        # thinking means no thinking blocks are produced, so there is nothing to
        # mangle. Override with FACTORY_CLAUDE_MAX_THINKING_TOKENS (e.g. once a
        # newer CLI fixes the cross-turn preservation).
        env["MAX_THINKING_TOKENS"] = os.environ.get("FACTORY_CLAUDE_MAX_THINKING_TOKENS", "0")
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


def _extract_tool_callables(tools: list[Any]) -> dict[str, dict[str, Any]]:
    """Build the {name: {function, description, input_schema}} dict the
    in-process MCP server expects, from whatever shape `tools` came in
    as. Supports two shapes:

      1. activegraph Tool objects: have .name + .function + (optional)
         .description + .input_schema attributes. Common when caller is
         the runtime passing actual @tool-decorated callables.
      2. Plain dicts: {name, description, input_schema, function}.
         The `function` key is REQUIRED for in-process invocation; dicts
         without it can't be served and the caller gets NotImplementedError.
    """
    out: dict[str, dict[str, Any]] = {}
    for tool in tools or []:
        if hasattr(tool, "name") and (hasattr(tool, "function") or callable(getattr(tool, "func", None))):
            fn = getattr(tool, "function", None) or getattr(tool, "func", None)
            if fn is None:
                continue
            out[tool.name] = {
                "function": fn,
                "description": getattr(tool, "description", "") or "",
                "input_schema": getattr(tool, "input_schema", None) or {"type": "object", "properties": {}},
            }
        elif isinstance(tool, dict) and "function" in tool and callable(tool["function"]):
            out[tool["name"]] = {
                "function": tool["function"],
                "description": tool.get("description", "") or "",
                "input_schema": tool.get("input_schema") or {"type": "object", "properties": {}},
            }
        # Dict-without-function shape is intentionally ignored here so
        # complete() can fall through to NotImplementedError.
    return out


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
