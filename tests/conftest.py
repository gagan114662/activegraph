"""Shared fixtures. Most tests want a clean global behavior + tool registry."""

import pytest

from activegraph import clear_registry, clear_tool_registry


@pytest.fixture(autouse=True)
def _isolate_registry():
    clear_registry()
    clear_tool_registry()
    yield
    clear_registry()
    clear_tool_registry()
