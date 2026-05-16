"""Smoke test for examples/resume_and_fork.py — the v0.5 contract example.

If this drifts from the README's `Replay and resume` story, fix one or the
other in the same commit. CONTRACT v0.5 #20 — the example is the contract.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_resume_and_fork_example_runs(tmp_path, monkeypatch):
    monkeypatch.chdir(Path(__file__).parent.parent)
    # The example pins DB to /tmp/...; we tolerate that.
    result = subprocess.run(
        [sys.executable, "examples/resume_and_fork.py"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"example crashed:\n--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    out = result.stdout
    # Sanity checks on the demo flow.
    assert "[step 1] paused" in out
    assert "[step 2] loaded" in out
    assert "[step 2] resumed to idle" in out
    assert "[step 3] forked" in out
    assert "diff: parent vs fork" in out
    assert "shared events:" in out
    assert "fork-only events:" in out
