"""Shared fixtures. Most tests want a clean global behavior registry."""

import pytest

from activegraph import clear_registry


@pytest.fixture(autouse=True)
def _isolate_registry():
    clear_registry()
    yield
    clear_registry()
