"""CLI flag drift detection tests — CONTRACT v1.1 #2.

This test suite verifies that CLI flags mentioned in documentation actually
exist in the CLI implementation, and that no flags exist without documentation.

Drift cases tested:
1. Definition leak: flag defined in code but not exposed at runtime
2. Runtime leak: flag available at runtime but not defined in documentation
3. Metadata mismatch: flag exists but type/default/description has changed
4. Synthetic drift: injected test fixtures simulating realistic drift scenarios
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import pytest


# ============================================================================
# FIXTURES: Synthetic CLI and Documentation States
# ============================================================================


@pytest.fixture
def fixtures_dir() -> Path:
    """Return path to synthetic drift test fixtures directory."""
    base = Path(__file__).parent / "fixtures" / "cli_drift_synthetic"
    base.mkdir(parents=True, exist_ok=True)
    return base


@pytest.fixture
def fixture_clean_cli(fixtures_dir: Path) -> Path:
    """Synthetic fixture: CLI with well-defined flags, docs in sync.

    Returns path to a fixture directory containing:
    - cli_clean.py: CLI definition with --inspect, --verbose, --output
    - docs_clean.md: Documentation referencing exactly those flags
    """
    fixture_path = fixtures_dir / "clean_cli_sync"
    fixture_path.mkdir(exist_ok=True)

    cli_file = fixture_path / "cli_clean.py"
    cli_file.write_text("""
# Synthetic clean CLI definition
flags = {
    "--inspect": {"type": "flag", "default": False, "description": "Show inspection details"},
    "--verbose": {"type": "flag", "default": False, "description": "Enable verbose output"},
    "--output": {"type": "string", "default": ".", "description": "Output directory"},
}
""")

    docs_file = fixture_path / "docs_clean.md"
    docs_file.write_text("""
# CLI Usage

Use `--inspect` to show inspection details.

The `--verbose` flag enables verbose output.

Specify the `--output` directory for results.
""")

    return fixture_path


@pytest.fixture
def fixture_definition_leak(fixtures_dir: Path) -> Path:
    """Synthetic fixture: flag in code but missing from docs (definition leak).

    Returns path to a fixture containing:
    - cli_leak_def.py: defines --internal flag not mentioned in docs
    - docs_leak_def.md: mentions only --inspect, --verbose

    This simulates: developer adds a CLI flag but forgets to document it.
    """
    fixture_path = fixtures_dir / "definition_leak_scenario"
    fixture_path.mkdir(exist_ok=True)

    cli_file = fixture_path / "cli_leak_def.py"
    cli_file.write_text("""
# CLI with undocumented internal flag
flags = {
    "--inspect": {"type": "flag", "default": False},
    "--verbose": {"type": "flag", "default": False},
    "--internal": {"type": "flag", "default": False, "description": "INTERNAL USE ONLY"},
}
""")

    docs_file = fixture_path / "docs_leak_def.md"
    docs_file.write_text("""
# CLI Usage

The `--inspect` flag shows inspection details.

The `--verbose` flag enables verbose output.
""")

    return fixture_path


@pytest.fixture
def fixture_runtime_leak(fixtures_dir: Path) -> Path:
    """Synthetic fixture: flag in docs but missing from code (runtime leak).

    Returns path to a fixture containing:
    - cli_leak_runtime.py: defines only --inspect, --verbose
    - docs_leak_runtime.md: mentions --inspect, --verbose, AND --async

    This simulates: docs promised a feature but the CLI flag was never shipped.
    """
    fixture_path = fixtures_dir / "runtime_leak_scenario"
    fixture_path.mkdir(exist_ok=True)

    cli_file = fixture_path / "cli_leak_runtime.py"
    cli_file.write_text("""
# CLI implementation missing promised --async flag
flags = {
    "--inspect": {"type": "flag", "default": False},
    "--verbose": {"type": "flag", "default": False},
}
""")

    docs_file = fixture_path / "docs_leak_runtime.md"
    docs_file.write_text("""
# CLI Usage

The `--inspect` flag shows inspection details.

The `--verbose` flag enables verbose output.

Use the `--async` flag to run asynchronously.
""")

    return fixture_path


@pytest.fixture
def fixture_metadata_mismatch(fixtures_dir: Path) -> Path:
    """Synthetic fixture: flag exists but metadata changed (type/default/description).

    Returns path to a fixture containing:
    - cli_mismatch.py: --timeout accepts int, defaults to 30
    - docs_mismatch.md: documents --timeout as string defaulting to "30s"

    This simulates: implementation refactored parameter semantics but docs weren't updated.
    """
    fixture_path = fixtures_dir / "metadata_mismatch_scenario"
    fixture_path.mkdir(exist_ok=True)

    cli_file = fixture_path / "cli_mismatch.py"
    cli_file.write_text("""
# CLI with metadata drift in --timeout flag
flags = {
    "--timeout": {"type": "int", "default": 30, "description": "Timeout in seconds"},
}
""")

    docs_file = fixture_path / "docs_mismatch.md"
    docs_file.write_text("""
# CLI Options

The `--timeout` parameter accepts a duration string like "30s" or "2m".

Default is `--timeout "30s"` (30 seconds).
""")

    return fixture_path


@pytest.fixture
def fixture_multiple_drifts(fixtures_dir: Path) -> Path:
    """Synthetic fixture: multiple drift types in one scenario.

    Returns path to a fixture containing multiple drift issues:
    - Undocumented --debug flag (definition leak)
    - Documented --retry but not implemented (runtime leak)
    - --timeout type mismatch (metadata drift)
    """
    fixture_path = fixtures_dir / "multiple_drifts_scenario"
    fixture_path.mkdir(exist_ok=True)

    cli_file = fixture_path / "cli_multi_drift.py"
    cli_file.write_text("""
# CLI with multiple drift issues
flags = {
    "--inspect": {"type": "flag", "default": False},
    "--debug": {"type": "flag", "default": False, "description": "Debug mode"},
    "--timeout": {"type": "int", "default": 30},
}
""")

    docs_file = fixture_path / "docs_multi_drift.md"
    docs_file.write_text("""
# CLI Reference

Use `--inspect` to enable inspection.

The `--retry` flag allows you to retry on failure.

Set `--timeout` to a duration string like "30s".
""")

    return fixture_path


# ============================================================================
# TESTS: Flag Extraction and Comparison
# ============================================================================


def extract_flags_from_cli(cli_path: Path) -> set[str]:
    """Extract flag names from synthetic CLI definition file.

    Parses a Python file defining a 'flags' dict and returns all flag names.

    Args:
        cli_path: Path to CLI Python file with flags dict

    Returns:
        Set of flag names (e.g., {"--inspect", "--verbose"})

    Raises:
        FileNotFoundError: if cli_path doesn't exist
        AssertionError: if flags dict cannot be parsed
    """
    if not cli_path.exists():
        raise FileNotFoundError(f"CLI file not found: {cli_path}")

    content = cli_path.read_text()
    # Extract flags dict using a simple approach
    # This is intentionally basic to test the gate behavior
    try:
        namespace: dict[str, Any] = {}
        exec(content, namespace)
        flags = namespace.get("flags", {})
        return set(flags.keys())
    except Exception as e:
        raise AssertionError(f"Failed to extract flags from {cli_path}: {e}")


def extract_flags_from_docs(docs_path: Path) -> set[str]:
    """Extract referenced flag names from markdown documentation.

    Looks for patterns like `--flagname` in backticks or as standalone words.

    Args:
        docs_path: Path to markdown documentation file

    Returns:
        Set of flag names (e.g., {"--inspect", "--verbose"})

    Raises:
        FileNotFoundError: if docs_path doesn't exist
    """
    if not docs_path.exists():
        raise FileNotFoundError(f"Docs file not found: {docs_path}")

    content = docs_path.read_text()
    # Match --flagname patterns (with or without backticks)
    pattern = r'`?--[\w-]+`?'
    matches = re.findall(pattern, content)
    # Clean up backticks if present
    flags = set()
    for m in matches:
        cleaned = m.strip('`')
        if cleaned.startswith('--'):
            flags.add(cleaned)
    return flags


# ============================================================================
# TEST CASES: Drift Detection
# ============================================================================


class TestFlagDriftDetection:
    """Test suite for CLI flag drift detection."""

    def test_clean_state_no_drift(self, fixture_clean_cli: Path) -> None:
        """PASS: CLI and docs in sync — no drift detected.

        This is a baseline test showing the normal healthy state where
        every CLI flag is documented and every documented flag exists.
        """
        cli_file = fixture_clean_cli / "cli_clean.py"
        docs_file = fixture_clean_cli / "docs_clean.md"

        cli_flags = extract_flags_from_cli(cli_file)
        doc_flags = extract_flags_from_docs(docs_file)

        # In the clean case, all CLI flags should be documented
        undocumented = cli_flags - doc_flags

        # This test should PASS (no drift)
        assert undocumented == set(), (
            f"CLI flags missing from docs: {undocumented}. "
            f"This indicates a definition leak (code drift)."
        )


class TestDefinitionLeak:
    """Tests for definition leak: CLI flag exists but is missing from docs."""

    def test_detects_undocumented_internal_flag(self, fixture_definition_leak: Path) -> None:
        """FAIL: Internal flag defined in code but missing from docs.

        Definition leak scenario: developer adds --internal flag to CLI
        but forgets to add it to the documentation. The drift gate should
        catch this and fail.

        This test MUST fail because the --internal flag appears in the CLI
        but not in the documentation.
        """
        cli_file = fixture_definition_leak / "cli_leak_def.py"
        docs_file = fixture_definition_leak / "docs_leak_def.md"

        cli_flags = extract_flags_from_cli(cli_file)
        doc_flags = extract_flags_from_docs(docs_file)

        # Definition leak: CLI flags not in docs
        undocumented = cli_flags - doc_flags

        # This MUST fail to catch the drift
        assert undocumented == set(), (
            f"Definition leak detected: {undocumented} in CLI but missing from docs. "
            f"All CLI flags must be documented."
        )


class TestRuntimeLeak:
    """Tests for runtime leak: documentation mentions a flag that doesn't exist."""

    def test_detects_promised_but_missing_async_flag(self, fixture_runtime_leak: Path) -> None:
        """FAIL: Docs promise --async flag but CLI doesn't implement it.

        Runtime leak scenario: documentation advertises an --async flag
        that users expect, but the CLI implementation doesn't provide it.
        Users get AttributeError on first try. The drift gate should catch
        this before it ships.

        This test MUST fail because docs reference --async but the CLI
        doesn't define it.
        """
        cli_file = fixture_runtime_leak / "cli_leak_runtime.py"
        docs_file = fixture_runtime_leak / "docs_leak_runtime.md"

        cli_flags = extract_flags_from_cli(cli_file)
        doc_flags = extract_flags_from_docs(docs_file)

        # Runtime leak: docs mention flags not in CLI
        promised_but_missing = doc_flags - cli_flags

        # This MUST fail to catch the drift
        assert promised_but_missing == set(), (
            f"Runtime leak detected: {promised_but_missing} in docs but missing from CLI. "
            f"All documented flags must be implemented."
        )


class TestMetadataMismatch:
    """Tests for metadata drift: flag exists but type/default/description changed."""

    def test_detects_timeout_type_mismatch(self, fixture_metadata_mismatch: Path) -> None:
        """FAIL: --timeout type changed (int vs string) between code and docs.

        Metadata drift scenario: the --timeout flag was refactored from
        accepting duration strings ("30s", "2m") to accepting integer seconds,
        but the documentation wasn't updated. Users read the docs, try
        `--timeout "30s"`, and get a type error.

        This test MUST fail because the flag metadata doesn't match.

        NOTE: This test intentionally uses a simple flag-name match to
        demonstrate the class of drift. Full implementation should extract
        and compare type/default/description metadata.
        """
        cli_file = fixture_metadata_mismatch / "cli_mismatch.py"
        docs_file = fixture_metadata_mismatch / "docs_mismatch.md"

        cli_flags = extract_flags_from_cli(cli_file)
        doc_flags = extract_flags_from_docs(docs_file)

        # Flags must exist in both (name match passes)
        missing_in_cli = doc_flags - cli_flags
        missing_in_docs = cli_flags - doc_flags

        assert missing_in_cli == set(), (
            f"Documented flags missing from CLI: {missing_in_cli}"
        )
        assert missing_in_docs == set(), (
            f"CLI flags missing from docs: {missing_in_docs}"
        )

        # TODO: Metadata mismatch detection (type, default, description)
        # This is a FAIL placeholder — the full gate implementation should
        # extract and compare metadata, then fail here with actionable message.
        pytest.fail(
            "Metadata mismatch detected for --timeout: "
            "CLI expects int (seconds), docs promise string (e.g., '30s'). "
            "This will cause user errors on first use."
        )


class TestMultipleDrifts:
    """Tests for scenarios with multiple drift types occurring together."""

    def test_detects_combined_definition_and_runtime_leaks(self, fixture_multiple_drifts: Path) -> None:
        """FAIL: Multiple drift types in a single scenario.

        Combined drift scenario:
        - Definition leak: --debug is defined in CLI but missing from docs
        - Runtime leak: --retry is documented but not implemented in CLI
        - Metadata drift: --timeout has mismatched type

        The drift gate must catch at least one of these issues (or all three).
        This test MUST fail.
        """
        cli_file = fixture_multiple_drifts / "cli_multi_drift.py"
        docs_file = fixture_multiple_drifts / "docs_multi_drift.md"

        cli_flags = extract_flags_from_cli(cli_file)
        doc_flags = extract_flags_from_docs(docs_file)

        undocumented = cli_flags - doc_flags
        missing_from_cli = doc_flags - cli_flags

        # Collect all drift issues
        drift_issues = []

        if undocumented:
            drift_issues.append(f"Definition leaks (undocumented in CLI): {undocumented}")

        if missing_from_cli:
            drift_issues.append(f"Runtime leaks (not in CLI): {missing_from_cli}")

        assert not drift_issues, (
            "Multiple drift issues detected:\n" +
            "\n".join(f"  - {issue}" for issue in drift_issues)
        )


# ============================================================================
# TESTS: Error Handling and Boundary Conditions
# ============================================================================


class TestErrorHandling:
    """Tests for graceful error handling in flag extraction."""

    def test_missing_cli_file_raises_file_not_found(self, fixtures_dir: Path) -> None:
        """FAIL: CLI extraction fails gracefully when file doesn't exist."""
        missing_path = fixtures_dir / "nonexistent" / "cli.py"

        with pytest.raises(FileNotFoundError, match="CLI file not found"):
            extract_flags_from_cli(missing_path)

    def test_missing_docs_file_raises_file_not_found(self, fixtures_dir: Path) -> None:
        """FAIL: Docs extraction fails gracefully when file doesn't exist."""
        missing_path = fixtures_dir / "nonexistent" / "docs.md"

        with pytest.raises(FileNotFoundError, match="Docs file not found"):
            extract_flags_from_docs(missing_path)

    def test_invalid_cli_syntax_raises_assertion_error(self, fixtures_dir: Path) -> None:
        """FAIL: CLI extraction fails gracefully on syntax errors."""
        bad_cli = fixtures_dir / "bad_syntax" / "cli.py"
        bad_cli.parent.mkdir(parents=True, exist_ok=True)
        bad_cli.write_text("flags = { INVALID SYNTAX }")

        with pytest.raises(AssertionError, match="Failed to extract flags"):
            extract_flags_from_cli(bad_cli)


# ============================================================================
# TESTS: Integration with Real Project Structure
# ============================================================================


class TestRealProjectFlagDiscovery:
    """Integration tests against the actual activegraph CLI.

    These tests validate that the drift detection logic can extract
    flags from the real CLI and documentation. They are initially
    expected to FAIL because no drift gate implementation exists yet.
    """

    def test_extract_real_cli_flags_from_main_py(self) -> None:
        """Placeholder test: extract flags from activegraph/cli/main.py.

        This test is intended to FAIL at this stage because:
        1. No flag extraction function exists for real Click CLI yet
        2. The extracted flags should include: --run-id, --tail, --json, etc.

        The gate implementation will need to:
        - Import the Click CLI group
        - Walk the command hierarchy (cli.commands, cmd.params, etc.)
        - Extract flag names and metadata
        """
        pytest.fail(
            "Gate implementation needed: extract flags from real Click CLI "
            "(activegraph/cli/main.py). Should find flags like: "
            "--run-id, --tail, --json, --from, --to, --at-event, --label, "
            "--run-a, --run-b"
        )

    def test_scan_docs_for_promised_flags(self) -> None:
        """Placeholder test: scan activegraph/docs/ for flag references.

        This test is intended to FAIL because the scan logic doesn't exist.

        The gate implementation will need to:
        - Scan markdown files under activegraph/docs/
        - Also scan: CHANGELOG.md, CONTRACT.md, README.md, HANDOFF.md, CONTRIBUTING.md
        - Extract all --flagname references
        - Compare against real CLI flags

        Expected documented flags from project scope:
        - Existing: --run-id, --tail, --json, --from, --to, --at-event, --label, etc.
        - T3-pending (allowlist): --set, --memo, --search
        """
        pytest.fail(
            "Gate implementation needed: scan docs for flag references. "
            "Must scan activegraph/docs/**, CHANGELOG.md, CONTRACT.md, README.md, "
            "HANDOFF.md, CONTRIBUTING.md. Compare against real CLI flags."
        )

    def test_gate_passes_on_main_with_allowlist(self) -> None:
        """Placeholder test: full gate run against main branch with allowlist.

        This test is intended to FAIL until the allowlist is set up.

        Once implemented, the gate should:
        - Extract real CLI flags from activegraph/cli/main.py
        - Scan docs for promised flags
        - Apply allowlist (e.g., T3-pending: --set, --memo, --search)
        - Pass (exit 0) when no unexpected drift is found
        """
        pytest.fail(
            "Gate integration test: verify gate passes on main branch "
            "with allowlist for T3-pending flags (--set, --memo, --search). "
            "This requires both flag extraction and allowlist logic."
        )
