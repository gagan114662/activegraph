"""CLI happy paths and exit codes — CONTRACT v0.8 #12–#13."""

from __future__ import annotations

import json
import os
import tempfile

import pytest
from click.testing import CliRunner

from activegraph import Graph, Runtime, behavior, clear_registry
from activegraph.cli.main import (
    EXIT_CODES,
    EXIT_CORRUPTION,
    EXIT_DIVERGENCE,
    EXIT_GENERIC_ERROR,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_USAGE_ERROR,
    cli,
)


def _seed_run(path: str) -> str:
    clear_registry()

    @behavior(name="planner", on=["goal.created"])
    def planner(event, graph, ctx):
        graph.add_object("task", {"x": 1})

    g = Graph()
    rt = Runtime(g, persist_to=path)
    rt.run_goal("test")
    rt.save_state()
    return rt.run_id


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    yield path
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except FileNotFoundError:
            pass


@pytest.fixture
def runner():
    return CliRunner()


class TestExitCodes:
    def test_codes_table_documented(self):
        assert EXIT_CODES["ok"] == 0
        assert EXIT_CODES["generic_error"] == 1
        assert EXIT_CODES["usage_error"] == 2
        assert EXIT_CODES["not_found"] == 3
        assert EXIT_CODES["corruption"] == 4
        assert EXIT_CODES["divergence"] == 5


class TestInspect:
    def test_happy_path_text(self, temp_db, runner):
        run_id = _seed_run(temp_db)
        result = runner.invoke(cli, ["inspect", f"sqlite:///{temp_db}"])
        assert result.exit_code == EXIT_OK, result.output
        assert run_id in result.output
        assert "state:" in result.output

    def test_happy_path_json(self, temp_db, runner):
        run_id = _seed_run(temp_db)
        result = runner.invoke(
            cli, ["inspect", f"sqlite:///{temp_db}", "--json"]
        )
        assert result.exit_code == EXIT_OK, result.output
        obj = json.loads(result.output)
        assert obj["run_id"] == run_id
        assert "state" in obj
        assert "budget" in obj
        assert "recent_events" in obj

    def test_not_found_for_missing_store(self, temp_db, runner):
        result = runner.invoke(
            cli, ["inspect", "sqlite:////nonexistent/path.db"]
        )
        assert result.exit_code == EXIT_NOT_FOUND, result.output

    def test_usage_error_for_bare_path(self, temp_db, runner):
        _seed_run(temp_db)
        result = runner.invoke(cli, ["inspect", temp_db])
        assert result.exit_code == EXIT_USAGE_ERROR, result.output
        # Must point operator at the right form.
        assert "sqlite:///" in (result.output or "") + (result.stderr_bytes or b"").decode()

    def test_tail_arg_limits_events(self, temp_db, runner):
        _seed_run(temp_db)
        result = runner.invoke(
            cli,
            ["inspect", f"sqlite:///{temp_db}", "--tail", "2", "--json"],
        )
        assert result.exit_code == EXIT_OK, result.output
        obj = json.loads(result.output)
        assert len(obj["recent_events"]) == 2


class TestReplay:
    def test_happy_path(self, temp_db, runner):
        run_id = _seed_run(temp_db)
        result = runner.invoke(
            cli, ["replay", f"sqlite:///{temp_db}", "--run-id", run_id, "--json"]
        )
        assert result.exit_code == EXIT_OK, result.output
        obj = json.loads(result.output)
        assert obj["run_id"] == run_id
        assert obj["events"] > 0
        assert obj["objects"] >= 1


class TestFork:
    def test_happy_path(self, temp_db, runner):
        run_id = _seed_run(temp_db)
        # Find a fork point
        rt = Runtime.load(f"sqlite:///{temp_db}", run_id=run_id)
        fork_at = next(e.id for e in rt.graph.events if e.type == "object.created")
        result = runner.invoke(
            cli,
            [
                "fork", f"sqlite:///{temp_db}",
                "--run-id", run_id,
                "--at-event", fork_at,
                "--label", "test-fork",
                "--json",
            ],
        )
        assert result.exit_code == EXIT_OK, result.output
        obj = json.loads(result.output)
        assert obj["parent_run_id"] == run_id
        assert obj["new_run_id"]
        assert obj["events_copied"] > 0

    def test_not_found_for_missing_event(self, temp_db, runner):
        run_id = _seed_run(temp_db)
        result = runner.invoke(
            cli,
            [
                "fork", f"sqlite:///{temp_db}",
                "--run-id", run_id,
                "--at-event", "evt_does_not_exist",
            ],
        )
        assert result.exit_code == EXIT_NOT_FOUND, result.output


class TestDiff:
    def test_happy_path(self, temp_db, runner):
        run_id = _seed_run(temp_db)
        rt = Runtime.load(f"sqlite:///{temp_db}", run_id=run_id)
        fork_at = next(e.id for e in rt.graph.events if e.type == "object.created")
        fork = rt.fork(at_event=fork_at, label="diff-test")
        fork.save_state()
        result = runner.invoke(
            cli,
            [
                "diff", f"sqlite:///{temp_db}",
                "--run-a", run_id,
                "--run-b", fork.run_id,
                "--json",
            ],
        )
        assert result.exit_code == EXIT_OK, result.output
        obj = json.loads(result.output)
        assert obj["run_a"] == run_id
        assert obj["run_b"] == fork.run_id
        for k in (
            "shared_events", "parent_only_events", "fork_only_events",
            "divergent_objects", "divergent_relations",
        ):
            assert k in obj


class TestExportTrace:
    def test_jsonl_format_writes_one_event_per_line(self, temp_db, runner, tmp_path):
        run_id = _seed_run(temp_db)
        out_file = tmp_path / "trace.jsonl"
        result = runner.invoke(
            cli,
            [
                "export-trace", f"sqlite:///{temp_db}",
                "--run-id", run_id,
                "--format", "jsonl",
                "-o", str(out_file),
            ],
        )
        assert result.exit_code == EXIT_OK, result.output
        lines = out_file.read_text().splitlines()
        assert len(lines) > 0
        for ln in lines:
            obj = json.loads(ln)
            assert "id" in obj
            assert "type" in obj


class TestMigrate:
    def test_sqlite_to_sqlite_happy_path(self, temp_db, runner, tmp_path):
        run_id = _seed_run(temp_db)
        dst = str(tmp_path / "dst.db")
        result = runner.invoke(
            cli,
            [
                "migrate",
                "--from", f"sqlite:///{temp_db}",
                "--to", f"sqlite:///{dst}",
                "--json",
            ],
        )
        assert result.exit_code == EXIT_OK, result.output
        obj = json.loads(result.output)
        assert any(r["run_id"] == run_id and r["status"] == "ok" for r in obj["runs"])

    def test_usage_error_on_bare_path(self, temp_db, runner, tmp_path):
        _seed_run(temp_db)
        dst = str(tmp_path / "dst.db")
        result = runner.invoke(
            cli, ["migrate", "--from", temp_db, "--to", dst]
        )
        assert result.exit_code == EXIT_USAGE_ERROR, result.output
