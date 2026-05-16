"""Tools subpackage. CONTRACT v0.7.

A tool is a primitive — not buried inside an LLM behavior. The
`@tool` decorator registers a callable with a name, schemas, cost,
and a determinism flag. The runtime invokes tools via the same
event-sourced pattern as LLM calls: every invocation is a
`tool.requested` / `tool.responded` event pair, and replay reads
those back instead of re-invoking (unless `replay_reinvoke_deterministic`
is set and the tool is marked deterministic).

Public surface:

  Tool                       — registered tool metadata + body
  ToolContext                — passed to tool function bodies
  ToolCache                  — content-keyed replay cache
  RecordedToolProvider       — fixture-backed tool invoker for tests
  RecordingToolProvider      — wraps another invoker, persists fixtures
  ToolError                  — structured failure from a tool body
  MissingToolError           — raised at registration when an LLM
                               behavior references an unregistered tool
  UnknownToolError           — raised when the LLM requests a tool
                               the behavior didn't declare
  tool                       — decorator
  get_tool_registry          — global tool registry inspector
  clear_tool_registry        — registry reset (test hygiene)
  make_graph_query_tool      — factory binding a graph_query tool to a Graph
  web_fetch                  — reference tool: stdlib urllib-based URL fetcher
"""

from activegraph.tools.base import Tool
from activegraph.tools.cache import ToolCache
from activegraph.tools.context import ToolContext
from activegraph.tools.decorators import (
    clear_tool_registry,
    get_tool_registry,
    tool,
)
from activegraph.tools.errors import (
    MissingToolError,
    ToolError,
    UnknownToolError,
)
from activegraph.tools.graph_query import make_graph_query_tool
from activegraph.tools.recorded import (
    RecordedToolProvider,
    RecordingToolProvider,
)
from activegraph.tools.web_fetch import web_fetch

__all__ = [
    "MissingToolError",
    "RecordedToolProvider",
    "RecordingToolProvider",
    "Tool",
    "ToolCache",
    "ToolContext",
    "ToolError",
    "UnknownToolError",
    "clear_tool_registry",
    "get_tool_registry",
    "make_graph_query_tool",
    "tool",
    "web_fetch",
]
