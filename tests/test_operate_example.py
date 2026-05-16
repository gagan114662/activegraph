"""Integration test: examples/operate_a_run.py runs as written.

CONTRACT v0.8 #18: "Operator guide examples all execute as written".
If the example breaks, this test catches it. The example exercises
nearly every v0.8 surface end-to-end.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


EXAMPLE = Path(__file__).parent.parent / "examples" / "operate_a_run.py"


def test_example_runs_end_to_end():
    result = subprocess.run(
        [sys.executable, str(EXAMPLE)],
        capture_output=True,
        text=True,
        timeout=60,
        env={
            **__import__("os").environ,
            # Don't try to migrate to Postgres in the example test.
            "ACTIVEGRAPH_POSTGRES_URL": "",
        },
    )
    assert result.returncode == 0, (
        f"example exited {result.returncode}\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    out = result.stdout
    assert "[runtime.status snapshot]" in out
    assert "ok — CLI snapshot matches" in out
    assert "[cli] forking at" in out
    assert "[cli] diff parent vs fork" in out
    assert "[cli] export trace as JSONL" in out
    assert "[done] artifacts in" in out
