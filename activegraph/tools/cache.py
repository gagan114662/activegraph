"""Tool replay cache. CONTRACT v0.7 #3.

Mirror of `activegraph.llm.cache.LLMCache`. Keyed by
`sha256(canonical_json({tool_name, args_normalized}))`. Population
paths:

  * `ToolCache.from_events(events)` — used at `Runtime.load(...,
    replay_tool_cache=True)` and `runtime.fork(...,
    replay_tool_cache=True)`. Walks the recorded log and harvests
    every `tool.responded` whose preceding `tool.requested` carries
    `args_hash`.

  * `cache.record(args_hash, output, ...)` — same-run repeat-call
    insurance, called inline from the runtime's tool invocation path.

CONTRACT v0.7 (tool-determinism decision): serve-from-cache is the
default on replay for ALL tools, deterministic or not. The
`replay_reinvoke_deterministic=True` Runtime flag is the opt-in that
lets deterministic tools actually re-invoke during replay. The
reasoning is documented in CONTRACT.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, Optional

from activegraph.core.event import Event


def canonicalize_args(args: Any) -> Any:
    """Normalize tool args into a JSON-stable shape for hashing.

    - Pydantic v2 BaseModel instance → `model.model_dump(mode="json")`
    - dict / list / scalar → recursed, Decimals → canonical string
    - sort_keys at JSON-dump time guarantees ordering stability.
    """
    dump = getattr(args, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except TypeError:
            return dump()
    if isinstance(args, dict):
        return {k: canonicalize_args(v) for k, v in args.items()}
    if isinstance(args, list):
        return [canonicalize_args(v) for v in args]
    if isinstance(args, Decimal):
        return str(args)
    return args


def hash_tool_call(*, tool_name: str, args: Any) -> str:
    payload = {"tool": tool_name, "args": canonicalize_args(args)}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class CachedToolResponse:
    """A cached tool response. Mirrors `LLMResponse` in shape so the
    replay path can hydrate without re-invoking the tool.
    """

    output: Any  # JSON-serializable; runtime will re-validate via output_schema
    error: Optional[dict[str, Any]] = None  # None for success
    latency_seconds: float = 0.0
    cost_usd: Decimal = Decimal("0")
    cache_hit: bool = False
    requesting_event_id: Optional[str] = None


class ToolCache:
    def __init__(self) -> None:
        self._by_hash: dict[str, CachedToolResponse] = {}

    # ---- read ----

    def get(self, args_hash: str) -> Optional[CachedToolResponse]:
        entry = self._by_hash.get(args_hash)
        if entry is None:
            return None
        return CachedToolResponse(
            output=entry.output,
            error=dict(entry.error) if entry.error else None,
            latency_seconds=entry.latency_seconds,
            cost_usd=entry.cost_usd,
            cache_hit=True,
            requesting_event_id=entry.requesting_event_id,
        )

    def has(self, args_hash: str) -> bool:
        return args_hash in self._by_hash

    def __len__(self) -> int:
        return len(self._by_hash)

    # ---- write ----

    def record(
        self,
        args_hash: str,
        response: CachedToolResponse,
        *,
        requesting_event_id: Optional[str] = None,
    ) -> None:
        clean = CachedToolResponse(
            output=response.output,
            error=dict(response.error) if response.error else None,
            latency_seconds=response.latency_seconds,
            cost_usd=response.cost_usd,
            cache_hit=False,
            requesting_event_id=requesting_event_id or response.requesting_event_id,
        )
        self._by_hash[args_hash] = clean

    # ---- bulk-load from a recorded event log ----

    @classmethod
    def from_events(cls, events: Iterable[Event]) -> "ToolCache":
        cache = cls()
        events_list = list(events)
        by_id: dict[str, Event] = {e.id: e for e in events_list}
        for e in events_list:
            if e.type != "tool.responded":
                continue
            req_id = e.caused_by
            if req_id is None:
                continue
            req = by_id.get(req_id)
            if req is None or req.type != "tool.requested":
                continue
            args_hash = req.payload.get("args_hash")
            if not args_hash:
                continue
            cache.record(
                args_hash,
                CachedToolResponse(
                    output=e.payload.get("output"),
                    error=e.payload.get("error"),
                    latency_seconds=float(
                        e.payload.get("latency_seconds", 0.0) or 0.0
                    ),
                    cost_usd=_decimal(e.payload.get("cost_usd", "0")),
                ),
                requesting_event_id=req_id,
            )
        return cache


def _decimal(v: Any) -> Decimal:
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))
