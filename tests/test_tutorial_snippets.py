"""Tutorial-snippet execution gate — CONTRACT v1.0-rc2 finding B2.

The v1.0-rc1 user-test gate surfaced **B2**: the tutorial's step 7
fork snippet (`docs/quickstart.md`) crashed with
`MissingProviderError` because it called `Runtime.load(...)`
without an `llm_provider=` argument and the loaded diligence pack
has LLM behaviors.

The fix was a snippet update, but the underlying gap is that
nothing in CI executes the doc-page Python snippets end-to-end.
The CLI-flags gate (CONTRACT v1.1 #2) does the equivalent for
shell invocations; this test does the same for the tutorial's
fork-and-diff snippet.

This is a tactical down-payment on the full v1.1 #2 expansion
(spec-vs-impl drift gate covers Python doc snippets across the
doc surface). v1.0-rc2 scope is just step 7 — the one snippet
the user-test caught. The v1.1 generalization covers tutorial
and cookbook pages via opt-in annotation or an allowlist.

The test extracts the step-7 code block from the tutorial source,
runs it in a subprocess against the bundled fixtures, and asserts
exit 0 plus the expected stdout marker. Subprocess isolation is
intentional — the tutorial snippet must be self-contained (every
import declared, no implicit framework state) to be a useful
copy-paste artifact for first-time users.
"""

from __future__ import annotations

import io
import re
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
TUTORIAL_PATH = REPO_ROOT / "docs" / "quickstart.md"


def _extract_step_7_snippet() -> str:
    """Pull the `fork_and_diff.py` snippet out of the tutorial.

    The snippet is the only fenced ```python block under the
    ## 7. Fork and diff heading. Extracting via heading + first-fence
    rather than line numbers so the test stays robust against minor
    tutorial edits above the section.
    """
    text = TUTORIAL_PATH.read_text()
    sentinel = "## 7. Fork and diff"
    idx = text.find(sentinel)
    if idx == -1:
        pytest.fail(
            f"could not locate '{sentinel}' in {TUTORIAL_PATH}; "
            f"the step-7 fork snippet's home heading moved or was "
            f"renamed — update this test to match"
        )
    section = text[idx:]
    m = re.search(r"```python\n(.*?)\n```", section, re.DOTALL)
    if m is None:
        pytest.fail(
            f"could not find a ```python fenced block under "
            f"'{sentinel}' — the snippet's fence style changed or "
            f"the snippet was removed"
        )
    return m.group(1)


def _run_quickstart_fixture_mode() -> None:
    """Run `activegraph quickstart` (fixture mode) so the parent run's
    DB exists for the fork snippet to operate on."""
    from activegraph.cli.quickstart import run_fixture_mode

    buf = io.StringIO()
    rc = run_fixture_mode(stream=buf)
    assert rc == 0, "fixture-mode quickstart did not exit 0"


class TestTutorialFork:
    def test_step_7_snippet_runs_end_to_end_against_bundled_fixtures(
        self, tmp_path: Path
    ) -> None:
        """The step-7 snippet must run with exit 0 and print the
        expected `forked: quickstart_cautious` marker.

        Regression for CONTRACT v1.0-rc2 finding B2: the snippet
        previously crashed with `MissingProviderError` because it
        called `Runtime.load` without an `llm_provider=`. The fix
        passes `RecordedDiligenceProvider(companies=THREE_COMPANIES)`
        so the fork runs against the same fixture provider as the
        parent, with no API key required.
        """
        _run_quickstart_fixture_mode()
        snippet = _extract_step_7_snippet()
        script = tmp_path / "fork_and_diff.py"
        script.write_text(snippet)

        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            timeout=120,
        )
        assert result.returncode == 0, (
            f"step-7 snippet failed with exit {result.returncode}.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}\n"
            f"This is a B2-shape regression — the tutorial's executable "
            f"Python snippet drifted from shipped behavior. The v1.1 #2 "
            f"expansion (CONTRACT) is the gate that prevents recurrence "
            f"across the full doc surface; this test covers step 7 only."
        )
        assert "forked: quickstart_cautious" in result.stdout, (
            f"step-7 snippet exited 0 but did not print the expected "
            f"`forked: quickstart_cautious` marker.\n"
            f"stdout:\n{result.stdout}"
        )

    def test_step_7_snippet_is_idempotent_on_rerun(
        self, tmp_path: Path
    ) -> None:
        """The snippet must be re-runnable — running it twice should
        succeed both times. The cleanup-on-collision branch in the
        snippet ("Removed previous fork ... to re-run cleanly.")
        addresses the secondary issue from B2:
        `sqlite3.IntegrityError: UNIQUE constraint failed: runs.run_id`
        on re-run.
        """
        _run_quickstart_fixture_mode()
        snippet = _extract_step_7_snippet()
        script = tmp_path / "fork_and_diff.py"
        script.write_text(snippet)

        first = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            timeout=120,
        )
        assert first.returncode == 0, (
            f"first invocation failed:\nstdout:\n{first.stdout}\n"
            f"stderr:\n{first.stderr}"
        )

        second = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            timeout=120,
        )
        assert second.returncode == 0, (
            f"second invocation (idempotency check) failed:\n"
            f"stdout:\n{second.stdout}\n"
            f"stderr:\n{second.stderr}"
        )
        assert "Removed previous fork" in second.stdout, (
            f"second invocation succeeded but did not print the "
            f"cleanup notice. The snippet's cleanup branch did not "
            f"fire on a re-run — that's the B2 secondary-issue regression "
            f"vector.\nstdout:\n{second.stdout}"
        )
