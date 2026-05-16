"""Active Graph Runtime. Public API surface.

The graph is the world. Behaviors are physics. The trace is the proof.
"""

from activegraph.behaviors.base import Behavior, RelationBehavior
from activegraph.behaviors.decorators import (
    behavior,
    clear_registry,
    get_registry,
    relation_behavior,
)
from activegraph.core.clock import Clock, FrozenClock, TickingClock
from activegraph.core.event import Event
from activegraph.core.graph import Graph, Object, Relation
from activegraph.core.ids import IDGen
from activegraph.core.patch import Patch
from activegraph.core.view import View
from activegraph.frame import Frame
from activegraph.policy import Policy
from activegraph.runtime.budget import Budget
from activegraph.runtime.runtime import Runtime

__all__ = [
    "Behavior",
    "Budget",
    "Clock",
    "Event",
    "Frame",
    "FrozenClock",
    "Graph",
    "IDGen",
    "Object",
    "Patch",
    "Policy",
    "Relation",
    "RelationBehavior",
    "Runtime",
    "TickingClock",
    "View",
    "behavior",
    "clear_registry",
    "get_registry",
    "relation_behavior",
]

__version__ = "0.0.1"
