"""Mission context for a run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Frame:
    goal: str
    id: Optional[str] = None
    constraints: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
