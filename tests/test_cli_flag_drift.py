"""CLI flag drift gate tests — CONTRACT v1.1 #2.

Drives ``scripts/gate_cli_flag_drift`` against synthetic fixtures
(definition leak, runtime leak, multi-drift) and the real project
corpus. The gate's pure comparison surface (``compute_drift``) is
exercised on the fixtures so the assertions stay independent of the
real CLI; the extraction + allowlist surface is exercised end-to-end
against the live tree with the documented T3-pending allowlist.

Frame: ``t2-build-cli-flag-drift-gate`` (outer:c63e0f7).
Amendments: D-1 (inner:fd53455) static extraction; D-2 (inner:623717f)
TOML allowlist with rationale + expiry.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Gate module loader
# ---------------------------------------------------------------------------


def _load_gate_module() -> Any:
    """Load ``scripts/gate_cli_flag_drift`` without polluting ``sys.path``.

    The gate ships under ``scripts/`` which is not a package; importlib
    by path keeps the test isolated from PYTHONPATH ordering.
    """
    repo_root = Path(__file__).resolve().parent.parent
    gate_path = repo_root / "scripts" / "gate_cli_flag_drift.py"
    spec = importlib.util.spec_from_file_location("gate_cli_flag_drift", gate_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass can resolve cls.__module__.
    sys.modules["gate_cli_flag_drift"] = module
    spec.loader.exec_module(module)
    return module


gate = _load_gate_module()


# ---------------------------------------------------------------------------
# Fixtures: synthetic CLI / docs pairs for each drift class
# ---------------------------------------------------------------------------


@pytest.fixture
def fixtures_dir(tmp_path: Path) -> Path:
    """Return a temp scratch dir for synthetic drift fixtures.

    Using ``tmp_path`` (per-test) instead of a checked-in directory
    keeps the fixtures from drifting silently between runs.
    """
    base = tmp_path / "cli_drift_synthetic"
    base.mkdir(parents=True, exist_ok=True)
    return base


@pytest.fixture
def fixture_clean_cli(fixtures_dir: Path) -> Path:
    fixture_path = fixtures_dir / "clean_cli_sync"
    fixture_path.mkdir(exist_ok=True)
    (fixture_path / "cli_clean.py").write_text(
        """
flags = {
    "--inspect": {"type": "flag", "default": False},
    "--verbose": {"type": "flag", "default": False},
    "--output":  {"type": "string", "default": "."},
}
"""
    )
    (fixture_path / "docs_clean.md").write_text(
        """
# CLI Usage

Use `--inspect` to show inspection details.
The `--verbose` flag enables verbose output.
Specify the `--output` directory for results.
"""
    )
    return fixture_path


@pytest.fixture
def fixture_definition_leak(fixtures_dir: Path) -> Path:
    fixture_path = fixtures_dir / "definition_leak_scenario"
    fixture_path.mkdir(exist_ok=True)
    (fixture_path / "cli_leak_def.py").write_text(
        """
flags = {
    "--inspect": {"type": "flag", "default": False},
    "--verbose": {"type": "flag", "default": False},
    "--internal": {"type": "flag", "default": False},
}
"""
    )
    (fixture_path / "docs_leak_def.md").write_text(
        """
# CLI Usage

The `--inspect` flag shows inspection details.
The `--verbose` flag enables verbose output.
"""
    )
    return fixture_path


@pytest.fixture
def fixture_runtime_leak(fixtures_dir: Path) -> Path:
    fixture_path = fixtures_dir / "runtime_leak_scenario"
    fixture_path.mkdir(exist_ok=True)
    (fixture_path / "cli_leak_runtime.py").write_text(
        """
flags = {
    "--inspect": {"type": "flag", "default": False},
    "--verbose": {"type": "flag", "default": False},
}
"""
    )
    (fixture_path / "docs_leak_runtime.md").write_text(
        """
# CLI Usage

The `--inspect` flag shows inspection details.
The `--verbose` flag enables verbose output.
Use the `--async` flag to run asynchronously.
"""
    )
    return fixture_path


@pytest.fixture
def fixture_multiple_drifts(fixtures_dir: Path) -> Path:
    fixture_path = fixtures_dir / "multiple_drifts_scenario"
    fixture_path.mkdir(exist_ok=True)
    (fixture_path / "cli_multi_drift.py").write_text(
        """
flags = {
    "--inspect": {"type": "flag", "default": False},
    "--debug":   {"type": "flag", "default": False},
    "--timeout": {"type": "int",  "default": 30},
}
"""
    )
    (fixture_path / "docs_multi_drift.md").write_text(
        """
# CLI Reference

Use `--inspect` to enable inspection.
The `--retry` flag allows you to retry on failure.
Set `--timeout` to a duration string like "30s".
"""
    )
    return fixture_path


# ---------------------------------------------------------------------------
# Synthetic flag extractors (used to drive the gate's pure compute_drift)
# ---------------------------------------------------------------------------


def _flags_from_synthetic_cli(cli_path: Path) -> set[str]:
    """Return the keys of the ``flags = {...}`` dict in a synthetic CLI file."""
    namespace: dict[str, Any] = {}
    exec(cli_path.read_text(), namespace)
    return set(namespace["flags"].keys())


def _flags_from_doc(doc_path: Path) -> set[str]:
    """Return ``--flag`` references in a markdown file."""
    found: set[str] = set()
    for match in re.findall(r"`?--([a-z][a-z0-9-]*)`?", doc_path.read_text()):
        found.add(f"--{match}")
    return found


# ---------------------------------------------------------------------------
# Synthetic drift cases — assert the gate correctly identifies each drift
# ---------------------------------------------------------------------------


class TestSyntheticDriftDetection:
    """Synthetic-fixture exercise of ``gate.compute_drift``.

    Each scenario constructs known cli_flags / doc_flags sets and
    asserts the gate flagged exactly the drift the scenario embeds.
    """

    def test_clean_state_reports_no_drift(self, fixture_clean_cli: Path) -> None:
        cli_flags = _flags_from_synthetic_cli(fixture_clean_cli / "cli_clean.py")
        doc_flags = _flags_from_doc(fixture_clean_cli / "docs_clean.md")
        report = gate.compute_drift(cli_flags, doc_flags)
        assert report.is_clean
        assert report.undocumented == frozenset()
        assert report.promised_but_missing == frozenset()

    def test_definition_leak_surfaces_internal_flag(
        self, fixture_definition_leak: Path
    ) -> None:
        cli_flags = _flags_from_synthetic_cli(fixture_definition_leak / "cli_leak_def.py")
        doc_flags = _flags_from_doc(fixture_definition_leak / "docs_leak_def.md")
        report = gate.compute_drift(cli_flags, doc_flags)
        assert not report.is_clean
        assert "--internal" in report.undocumented
        assert report.promised_but_missing == frozenset()

    def test_runtime_leak_surfaces_async_flag(
        self, fixture_runtime_leak: Path
    ) -> None:
        cli_flags = _flags_from_synthetic_cli(fixture_runtime_leak / "cli_leak_runtime.py")
        doc_flags = _flags_from_doc(fixture_runtime_leak / "docs_leak_runtime.md")
        report = gate.compute_drift(cli_flags, doc_flags)
        assert not report.is_clean
        assert "--async" in report.promised_but_missing
        assert report.undocumented == frozenset()

    def test_multiple_drifts_surface_both_directions(
        self, fixture_multiple_drifts: Path
    ) -> None:
        cli_flags = _flags_from_synthetic_cli(fixture_multiple_drifts / "cli_multi_drift.py")
        doc_flags = _flags_from_doc(fixture_multiple_drifts / "docs_multi_drift.md")
        report = gate.compute_drift(cli_flags, doc_flags)
        assert not report.is_clean
        assert "--debug" in report.undocumented
        assert "--retry" in report.promised_but_missing

    def test_allowlist_suppresses_known_gap(
        self, fixture_runtime_leak: Path
    ) -> None:
        cli_flags = _flags_from_synthetic_cli(fixture_runtime_leak / "cli_leak_runtime.py")
        doc_flags = _flags_from_doc(fixture_runtime_leak / "docs_leak_runtime.md")
        report = gate.compute_drift(cli_flags, doc_flags, allowlisted={"--async"})
        assert report.is_clean
        assert "--async" in report.allowlisted


# ---------------------------------------------------------------------------
# Extraction surface — exercise the real regex + ast.parse path
# ---------------------------------------------------------------------------


class TestExtraction:
    """Cover the static extraction surface from D-1."""

    def test_extract_cli_flags_picks_up_click_options(self, tmp_path: Path) -> None:
        cli_dir = tmp_path / "cli"
        cli_dir.mkdir()
        (cli_dir / "main.py").write_text(
            "import click\n"
            "@click.command()\n"
            "@click.option('--alpha', default=None)\n"
            "@click.option('--beta-gamma', is_flag=True)\n"
            "def cmd(alpha, beta_gamma):\n"
            "    pass\n"
        )
        flags = gate.extract_cli_flags(cli_dir)
        assert {"--alpha", "--beta-gamma"}.issubset(flags)

    def test_extract_cli_flags_picks_up_click_option_with_short_first(
        self, tmp_path: Path
    ) -> None:
        # The shape that triggered the gate-vs-docs noise on real main.py:
        # @click.option("-o", "--output-dir", ...) — short form first.
        cli_dir = tmp_path / "cli"
        cli_dir.mkdir()
        (cli_dir / "main.py").write_text(
            "import click\n"
            "@click.command()\n"
            "@click.option('-o', '--output-dir', default='.')\n"
            "def cmd(output_dir):\n"
            "    pass\n"
        )
        flags = gate.extract_cli_flags(cli_dir)
        assert "--output-dir" in flags

    def test_extract_cli_flags_picks_up_add_argument(self, tmp_path: Path) -> None:
        cli_dir = tmp_path / "cli"
        cli_dir.mkdir()
        (cli_dir / "main.py").write_text(
            "import argparse\n"
            "p = argparse.ArgumentParser()\n"
            "p.add_argument('--solo')\n"
            "p.add_argument(\"--with-dash\")\n"
        )
        flags = gate.extract_cli_flags(cli_dir)
        assert {"--solo", "--with-dash"}.issubset(flags)

    def test_extract_cli_flags_includes_click_builtins(self, tmp_path: Path) -> None:
        # --help and --version are click defaults; the gate treats them
        # as real CLI flags so docs mentioning them don't trip the gate.
        cli_dir = tmp_path / "cli"
        cli_dir.mkdir()
        (cli_dir / "main.py").write_text("# empty CLI\n")
        flags = gate.extract_cli_flags(cli_dir)
        assert "--help" in flags
        assert "--version" in flags

    def test_extract_cli_flags_skips_pycache(self, tmp_path: Path) -> None:
        cli_dir = tmp_path / "cli"
        (cli_dir / "__pycache__").mkdir(parents=True)
        (cli_dir / "main.py").write_text(
            "p.add_argument('--real')\n"
        )
        (cli_dir / "__pycache__" / "stale.py").write_text(
            "p.add_argument('--ghost')\n"
        )
        flags = gate.extract_cli_flags(cli_dir)
        assert "--real" in flags
        assert "--ghost" not in flags

    def test_extract_cli_flags_fails_closed_on_syntax_error(self, tmp_path: Path) -> None:
        cli_dir = tmp_path / "cli"
        cli_dir.mkdir()
        (cli_dir / "broken.py").write_text("def f(:\n")
        with pytest.raises(gate.CliParseError):
            gate.extract_cli_flags(cli_dir)

    def test_extract_cli_flags_errors_on_missing_dir(self, tmp_path: Path) -> None:
        with pytest.raises(gate.GateError, match="CLI directory not found"):
            gate.extract_cli_flags(tmp_path / "nope")

    def test_extract_doc_flags_from_markdown(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text("Use `--set` like `--memo`, but also see --search and --verbose.\n")
        assert gate.extract_doc_flags([doc]) == {"--set", "--memo", "--search", "--verbose"}

    def test_extract_doc_flags_ignores_em_dashes_inside_words(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text(
            "pre--post should not be a flag, neither should foo--bar.\n"
            "but `--legit` is one.\n"
        )
        assert gate.extract_doc_flags([doc]) == {"--legit"}


# ---------------------------------------------------------------------------
# Allowlist surface — D-2 schema validation + expiry / resolution semantics
# ---------------------------------------------------------------------------


def _write_allowlist(path: Path, body: str) -> None:
    path.write_text(body)


class TestAllowlist:
    """Cover the allowlist surface from D-2."""

    def test_missing_file_returns_empty_set(self, tmp_path: Path) -> None:
        assert gate.load_allowlist(tmp_path / "absent.toml") == set()

    def test_well_formed_entry_loads(self, tmp_path: Path) -> None:
        path = tmp_path / "allow.toml"
        _write_allowlist(
            path,
            'schema_version = "1"\n'
            "[[entry]]\n"
            'flag = "--set"\n'
            'rationale = "Pending impl per t3."\n'
            'expiry_commit_ref = "frame:t3-implement-cli-set-flag"\n'
            'expiry_date = "2099-01-01"\n',
        )
        assert gate.load_allowlist(path, today=date(2026, 5, 22)) == {"--set"}

    def test_missing_rationale_is_malformed(self, tmp_path: Path) -> None:
        path = tmp_path / "allow.toml"
        _write_allowlist(
            path,
            'schema_version = "1"\n'
            "[[entry]]\n"
            'flag = "--set"\n'
            'expiry_date = "2099-01-01"\n',
        )
        with pytest.raises(gate.AllowlistEntryMalformedError, match="rationale"):
            gate.load_allowlist(path, today=date(2026, 5, 22))

    def test_missing_expiry_is_malformed(self, tmp_path: Path) -> None:
        path = tmp_path / "allow.toml"
        _write_allowlist(
            path,
            'schema_version = "1"\n'
            "[[entry]]\n"
            'flag = "--set"\n'
            'rationale = "Pending impl."\n',
        )
        with pytest.raises(gate.AllowlistEntryMalformedError, match="expiry_date"):
            gate.load_allowlist(path, today=date(2026, 5, 22))

    def test_wrong_schema_version_is_malformed(self, tmp_path: Path) -> None:
        path = tmp_path / "allow.toml"
        _write_allowlist(
            path,
            'schema_version = "2"\n'
            "[[entry]]\n"
            'flag = "--set"\n'
            'rationale = "x"\n'
            'expiry_date = "2099-01-01"\n',
        )
        with pytest.raises(gate.AllowlistEntryMalformedError, match="schema_version"):
            gate.load_allowlist(path, today=date(2026, 5, 22))

    def test_expired_entry_fails_closed(self, tmp_path: Path) -> None:
        path = tmp_path / "allow.toml"
        _write_allowlist(
            path,
            'schema_version = "1"\n'
            "[[entry]]\n"
            'flag = "--set"\n'
            'rationale = "Pending impl."\n'
            'expiry_date = "2020-01-01"\n',
        )
        with pytest.raises(gate.AllowlistEntryExpiredError) as excinfo:
            gate.load_allowlist(path, today=date(2026, 5, 22))
        assert excinfo.value.flag == "--set"

    def test_resolved_entry_fails_closed(self, tmp_path: Path) -> None:
        # Lay down a fake frames/<id>.status with "closed" so the
        # resolution backstop fires.
        path = tmp_path / "allow.toml"
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        (frames_dir / "t3-implement-cli-set-flag.status").write_text("closed\n")
        _write_allowlist(
            path,
            'schema_version = "1"\n'
            "[[entry]]\n"
            'flag = "--set"\n'
            'rationale = "Pending impl per t3."\n'
            'expiry_commit_ref = "frame:t3-implement-cli-set-flag"\n'
            'expiry_date = "2099-01-01"\n',
        )
        with pytest.raises(gate.AllowlistEntryResolvedError) as excinfo:
            gate.load_allowlist(path, today=date(2026, 5, 22), repo_root=tmp_path)
        assert excinfo.value.flag == "--set"
        assert excinfo.value.resolving_frame == "t3-implement-cli-set-flag"

    def test_shipped_allowlist_loads_against_repo(self) -> None:
        # The real allowlist on disk MUST be valid against today's
        # date and the live frame-status files. If it isn't, the gate
        # should fail closed -- this test surfaces that in CI.
        repo_root = Path(__file__).resolve().parent.parent
        allowlist = repo_root / "cli_flag_drift_allowlist.toml"
        assert allowlist.exists()
        loaded = gate.load_allowlist(allowlist, repo_root=repo_root)
        # T3 (v1.1) landed --set as a real CLI flag, so the allowlist no
        # longer carries it; --memo / --search remain pending.
        assert {"--memo", "--search"}.issubset(loaded)
        assert "--set" not in loaded


# ---------------------------------------------------------------------------
# Real project corpus — extraction + drift end-to-end against main
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parent.parent


class TestRealProjectFlagDiscovery:
    """End-to-end exercise against the real activegraph corpus."""

    def test_extract_real_cli_flags_from_main_py(self) -> None:
        cli_flags = gate.extract_cli_flags(REPO_ROOT / "activegraph" / "cli")
        # Spot-check a representative subset extracted from the click
        # decorators in activegraph/cli/main.py; the gate is allowed
        # to find more, but it must find at least these.
        expected = {
            "--run-id",
            "--tail",
            "--json",
            "--at-event",
            "--label",
            "--run-a",
            "--run-b",
            "--from",
            "--to",
        }
        missing = expected - cli_flags
        assert not missing, f"CLI extraction missed: {missing}"

    def test_scan_docs_for_promised_flags(self) -> None:
        doc_paths = gate._default_doc_paths(REPO_ROOT)
        assert doc_paths, "expected at least one doc path on real corpus"
        doc_flags = gate.extract_doc_flags(doc_paths)
        # The T3-pending cluster MUST appear in docs -- that's the
        # exact drift this gate was built to catch.
        assert {"--set", "--memo", "--search"}.issubset(doc_flags)

    def test_gate_passes_on_main_with_allowlist(self) -> None:
        report = gate.detect_drift(
            REPO_ROOT / "activegraph" / "cli",
            gate._default_doc_paths(REPO_ROOT),
            allowlist_path=REPO_ROOT / "cli_flag_drift_allowlist.toml",
            repo_root=REPO_ROOT,
        )
        assert report.is_clean, (
            f"Unexpected drift on main:\n"
            f"  undocumented           = {sorted(report.undocumented)}\n"
            f"  promised_but_missing   = {sorted(report.promised_but_missing)}\n"
            f"  allowlisted (suppress) = {sorted(report.allowlisted)}"
        )

    def test_gate_main_exit_code_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = gate.main([])
        captured = capsys.readouterr()
        assert exit_code == 0, (
            f"gate.main() exit={exit_code}; "
            f"stdout={captured.out!r}; stderr={captured.err!r}"
        )
