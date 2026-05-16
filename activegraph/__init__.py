"""Active Graph Runtime. Public API surface.

The graph is the world. Behaviors are physics. The trace is the proof.
"""

from activegraph.behaviors.base import Behavior, LLMBehavior, RelationBehavior
from activegraph.behaviors.decorators import (
    behavior,
    clear_registry,
    get_registry,
    llm_behavior,
    relation_behavior,
)
from activegraph.core.clock import Clock, FrozenClock, TickingClock
from activegraph.core.event import Event
from activegraph.core.graph import Graph, Object, Relation
from activegraph.core.ids import IDGen
from activegraph.core.patch import Patch
from activegraph.core.view import View
from activegraph.frame import Frame
from activegraph.llm.errors import LLMBehaviorError, MissingProviderError
from activegraph.policy import Policy
from activegraph.runtime.budget import Budget
from activegraph.runtime.diff import Diff, DivergentObject, DivergentRelation
from activegraph.runtime.errors import ReplayDivergenceError
from activegraph.runtime.patterns import UnsupportedPatternError
from activegraph.runtime.runtime import Runtime
from activegraph.store import (
    EventStore,
    InMemoryEventStore,
    InvalidStoreURL,
    NonSerializableEventError,
    RunRecord,
    SQLiteEventStore,
    open_store,
    parse_store_url,
)
# v0.7 public surface for tools
from activegraph.tools import (
    MissingToolError,
    Tool,
    ToolContext,
    ToolError,
    UnknownToolError,
    clear_tool_registry,
    get_tool_registry,
    tool,
)
# v0.8 observability surface
from activegraph.observability import (
    Metrics,
    MigrationReport,
    MigrationRunReport,
    NoOpMetrics,
    PrometheusMetrics,
    RuntimeStatus,
    configure_logging,
    migrate,
)

__all__ = [
    "Behavior",
    "Budget",
    "Clock",
    "Diff",
    "DivergentObject",
    "DivergentRelation",
    "Event",
    "EventStore",
    "Frame",
    "FrozenClock",
    "Graph",
    "IDGen",
    "InMemoryEventStore",
    "InvalidStoreURL",
    "LLMBehavior",
    "LLMBehaviorError",
    "Metrics",
    "MigrationReport",
    "MigrationRunReport",
    "MissingProviderError",
    "MissingToolError",
    "NoOpMetrics",
    "NonSerializableEventError",
    "Object",
    "Patch",
    "Policy",
    "PrometheusMetrics",
    "Relation",
    "RelationBehavior",
    "ReplayDivergenceError",
    "RunRecord",
    "Runtime",
    "RuntimeStatus",
    "SQLiteEventStore",
    "TickingClock",
    "Tool",
    "ToolContext",
    "ToolError",
    "UnknownToolError",
    "UnsupportedPatternError",
    "View",
    "behavior",
    "clear_registry",
    "clear_tool_registry",
    "configure_logging",
    "get_registry",
    "get_tool_registry",
    "llm_behavior",
    "migrate",
    "open_store",
    "parse_store_url",
    "relation_behavior",
    "tool",
]

__version__ = "0.8.0"
