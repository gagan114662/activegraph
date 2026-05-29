"""T7 medium run 021 coverage for ``activegraph.trace.printer.Trace.export``.

``Trace.export`` writes the human-readable trace (one formatted line per event,
as produced by ``Trace.lines()``) to a file, each line terminated by ``\\n``.
This is distinct from ``Runtime.export_trace`` (JSONL), which is the only export
path the existing suite covered. These tests exercise the formatted-line export
directly with real ``Graph``/``Runtime`` fixtures (no mocks of the API under test):

* happy path  -> one written line per graph event, content matches ``lines()``
* boundary    -> empty graph produces an empty file (no spurious newline content)
* overwrite   -> exporting onto an existing file truncates, not appends
"""

from activegraph import FrozenClock, Graph, IDGen, Runtime, behavior
from activegraph.trace.printer import Trace


def _graph_with_events() -> Graph:
    """Build a real graph carrying a handful of events via a behavior run."""

    @behavior(name="t7m021", on=["goal.created"])
    def _emit(event, graph, ctx):
        graph.add_object("task", {"title": "ship"})

    g = Graph(ids=IDGen(), clock=FrozenClock())
    Runtime(g).run_goal("hello")
    return g


def test_trace_export_writes_one_line_per_event(tmp_path):
    """Happy path: export writes exactly len(lines) rows matching lines()."""
    g = _graph_with_events()
    trace = Trace(g)
    expected = trace.lines()
    assert expected, "fixture graph should have produced events"

    out = tmp_path / "trace.txt"
    trace.export(str(out))

    written = out.read_text().splitlines()
    assert written == expected
    assert len(written) == len(list(g.events))
    # File ends with a trailing newline because each line is written with "\n".
    assert out.read_text().endswith("\n")


def test_trace_export_empty_graph_writes_empty_file(tmp_path):
    """Boundary: a graph with no events yields a zero-length export file."""
    g = Graph(ids=IDGen(), clock=FrozenClock())
    trace = Trace(g)
    assert trace.lines() == []

    out = tmp_path / "empty.txt"
    trace.export(str(out))

    assert out.exists()
    assert out.read_text() == ""


def test_trace_export_overwrites_existing_file(tmp_path):
    """Boundary: export opens with mode 'w', so it truncates prior content."""
    out = tmp_path / "trace.txt"
    out.write_text("STALE CONTENT THAT MUST NOT SURVIVE\n" * 10)

    g = _graph_with_events()
    trace = Trace(g)
    trace.export(str(out))

    written = out.read_text()
    assert "STALE CONTENT" not in written
    assert written.splitlines() == trace.lines()
