"""T7 HARD repetition run 007 — docstring↔code drift regression test.

`migrate()`'s docstring (activegraph/observability/migration.py:83) promises:

    "The overall operation is considered successful iff every run's status
     is ``"ok"`` or ``"skipped"``."

That is an ALLOWLIST contract: `MigrationReport.ok` must be True iff EVERY
run's status is in {"ok", "skipped"}.

The implementation drifted to a BLOCKLIST: `all(r.status != "failed" ...)`.
A blocklist treats *any* status that isn't the literal string "failed" as
success — including an unknown/future/typo'd status the docstring never
sanctioned. That breaks the documented "iff ok or skipped" guarantee.

These tests assert the documented allowlist behavior; the "unknown status"
case FAILS against the blocklist implementation and PASSES once `ok` is
rewritten to the allowlist the docstring describes.
"""

from activegraph.observability.migration import MigrationReport, MigrationRunReport


def _report(*statuses: str) -> MigrationReport:
    runs = tuple(
        MigrationRunReport(run_id=f"r{i}", status=s, events_migrated=0)
        for i, s in enumerate(statuses)
    )
    return MigrationReport(source_url="sqlite:///a", dest_url="sqlite:///b", runs=runs)


def test_ok_true_when_all_ok():
    assert _report("ok", "ok").ok is True


def test_ok_true_when_ok_and_skipped():
    # The docstring explicitly sanctions "skipped" as a success status.
    assert _report("ok", "skipped").ok is True


def test_ok_false_when_any_failed():
    assert _report("ok", "failed").ok is False


def test_ok_false_for_unknown_status():
    # DOCUMENTED behavior: ok iff every status is "ok" or "skipped".
    # An unrecognized status is NOT in that allowlist, so the operation
    # must NOT be reported successful. The blocklist implementation
    # (status != "failed") wrongly returns True here.
    assert _report("ok", "partial").ok is False


def test_ok_false_for_empty_status():
    assert _report("ok", "").ok is False
