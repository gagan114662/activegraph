"""Hard limits on a run. When any limit is hit the runtime stops gracefully
and emits runtime.budget_exhausted.
"""

from __future__ import annotations

import time
from typing import Any, Optional


KNOWN_LIMITS = (
    "max_events",
    "max_behavior_calls",
    "max_llm_calls",
    "max_tool_calls",
    "max_patches",
    "max_depth",
    "max_seconds",
    "max_cost_usd",
)


class Budget:
    def __init__(self, limits: Optional[dict[str, Any]] = None) -> None:
        self.limits: dict[str, float] = {}
        for k in KNOWN_LIMITS:
            v = (limits or {}).get(k)
            self.limits[k] = float(v) if v is not None else float("inf")
        self.used: dict[str, float] = {k: 0.0 for k in self.limits}
        self._start: Optional[float] = None
        self._exhausted_by: Optional[str] = None

    def start(self) -> None:
        self._start = time.monotonic()

    def consume(self, key: str, amount: float = 1.0) -> None:
        self.used[key] = self.used.get(key, 0.0) + amount

    def exhausted_by(self) -> Optional[str]:
        return self._exhausted_by

    def remaining(self) -> bool:
        for k, limit in self.limits.items():
            if k == "max_seconds":
                if self._start is None:
                    continue
                if time.monotonic() - self._start >= limit:
                    self._exhausted_by = k
                    return False
                continue
            if self.used.get(k, 0.0) >= limit:
                self._exhausted_by = k
                return False
        return True

    def snapshot(self) -> dict[str, Any]:
        out = {"used": dict(self.used), "limits": {}}
        for k, v in self.limits.items():
            out["limits"][k] = None if v == float("inf") else v
        return out
