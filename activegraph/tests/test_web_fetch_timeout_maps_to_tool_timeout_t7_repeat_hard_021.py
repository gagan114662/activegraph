"""T7 repeat hard 021 — docstring↔code drift in `activegraph.tools.web_fetch`.

DOCUMENTED BEHAVIOR (the drift):
    `web_fetch` documents — via the explicit ``raise ToolError("tool.timeout", ...)``
    clause in its body (activegraph/tools/web_fetch.py) — that a request timeout
    surfaces as the structured reason ``tool.timeout`` (the v0.7 timeout code,
    distinct from ``tool.network_error``).

THE BUG:
    `urllib.request.urlopen(..., timeout=...)` does NOT raise a bare
    ``TimeoutError`` on timeout — it raises ``urllib.error.URLError`` whose
    ``.reason`` is a ``TimeoutError`` (verified: ``URLError`` is itself NOT a
    ``TimeoutError``). The ``except urllib.error.URLError`` clause is ordered
    BEFORE the ``except TimeoutError`` clause, so a real timeout is caught by
    the URLError handler and mislabeled ``tool.network_error``. The
    ``except TimeoutError`` clause is dead code for urllib timeouts.

    Net effect: the documented ``tool.timeout`` mapping never fires for the
    actual transport this tool uses. A caller distinguishing "the host is
    unreachable" (network_error) from "the host was too slow" (timeout) —
    exactly what the two separate reason codes exist for — gets the wrong code.

This test asserts the DOCUMENTED behavior and FAILS against the current code
(it will see ``tool.network_error``). The fix re-routes a timeout-caused
URLError to ``tool.timeout``.
"""

from __future__ import annotations

import socket
import urllib.error

import pytest

from activegraph.tools.errors import ToolError
from activegraph.tools.web_fetch import WebFetchInput, web_fetch

# `web_fetch` is wrapped by the @tool decorator into a `Tool`; its body is
# `web_fetch.fn` (matches how tests/test_tools.py exercises tool bodies).
web_fetch_fn = web_fetch.fn


class _FakeCtx:
    """Minimal ToolContext stand-in — web_fetch only needs an object to
    accept as `ctx`; it does not read any attribute off it on the timeout
    path."""


def _install_timeout_urlopen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make urlopen behave the way the real stdlib does on a timeout:
    raise URLError wrapping a socket.timeout (a TimeoutError subclass)."""

    def _raise_timeout(req, timeout=None):  # noqa: ANN001 - test shim
        # This mirrors what urllib actually does: the socket-level timeout
        # bubbles up wrapped in URLError, NOT as a bare TimeoutError.
        raise urllib.error.URLError(reason=socket.timeout("timed out"))

    monkeypatch.setattr(
        "urllib.request.urlopen", _raise_timeout, raising=True
    )


def test_web_fetch_timeout_maps_to_tool_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_timeout_urlopen(monkeypatch)

    args = WebFetchInput(url="http://example.invalid/", timeout_seconds=0.01)

    with pytest.raises(ToolError) as excinfo:
        web_fetch_fn(args, _FakeCtx())

    # Documented contract: a timeout is reason `tool.timeout`, NOT
    # `tool.network_error`.
    assert excinfo.value.reason == "tool.timeout", (
        f"timeout should map to 'tool.timeout' per the documented behavior, "
        f"got {excinfo.value.reason!r}"
    )


def test_web_fetch_genuine_network_error_still_maps_to_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guard the fix against over-correction: a NON-timeout URLError
    (e.g. DNS / connection refused) must still map to `tool.network_error`."""

    def _raise_dns_failure(req, timeout=None):  # noqa: ANN001 - test shim
        raise urllib.error.URLError(reason=socket.gaierror("Name or service not known"))

    monkeypatch.setattr(
        "urllib.request.urlopen", _raise_dns_failure, raising=True
    )

    args = WebFetchInput(url="http://example.invalid/", timeout_seconds=10.0)

    with pytest.raises(ToolError) as excinfo:
        web_fetch_fn(args, _FakeCtx())

    assert excinfo.value.reason == "tool.network_error", (
        f"a non-timeout URLError must remain 'tool.network_error', "
        f"got {excinfo.value.reason!r}"
    )
