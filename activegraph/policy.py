"""Per-behavior policy. v0 is permissive — fields are recorded but not enforced
beyond a couple of obvious checks. Hardening lands in v0.6 alongside LLM
behaviors, where unbounded tool/cost spend is the real risk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Policy:
    behavior: Optional[str] = None
    can_create: list[str] = field(default_factory=list)
    can_create_relation: list[str] = field(default_factory=list)
    can_propose: list[str] = field(default_factory=list)
    can_apply: list[str] = field(default_factory=list)
    can_call_tool: list[str] = field(default_factory=list)
    requires_approval: list[str] = field(default_factory=list)
