"""T7 medium run 020 coverage for
``activegraph.observability.migration.MigrationReport.failures``.

The ``MigrationReport.failures`` property derives the subset of per-run
reports whose ``status == "failed"``. Existing migration tests assert
``report.ok`` via full end-to-end migration runs, but never exercise
``.failures`` directly nor construct ``MigrationReport`` from real
``MigrationRunReport`` fixtures to verify which runs it surfaces.

These tests use real dataclass fixtures (no mocks of the API under test)
to cover the happy path (mixed statuses -> only the failed run is
returned) plus boundary/error behavior (empty report, all-ok report,
all-failed report, and that "skipped" is NOT treated as a failure).
"""

from __future__ import annotations

from activegraph.observability.migration import (
    MigrationReport,
    MigrationRunReport,
)


def _run(run_id: str, status: str) -> MigrationRunReport:
    """Build a real MigrationRunReport fixture for the given status."""
    return MigrationRunReport(
        run_id=run_id,
        status=status,
        events_migrated=0 if status == "failed" else 3,
        error="boom" if status == "failed" else None,
    )


def test_activegraph_observability_migration_MigrationReport_failures_returns_only_failed_runs() -> None:
    """Happy path: a mixed report surfaces exactly the failed run(s)."""
    ok_run = _run("run-ok", "ok")
    skipped_run = _run("run-skipped", "skipped")
    failed_run = _run("run-failed", "failed")

    report = MigrationReport(
        source_url="sqlite:///src.db",
        dest_url="sqlite:///dst.db",
        runs=(ok_run, skipped_run, failed_run),
    )

    failures = report.failures

    # Only the failed run is returned, as a tuple, preserving identity.
    assert failures == (failed_run,)
    assert all(r.status == "failed" for r in failures)
    # The derived view is consistent with .ok: a failure means not ok.
    assert report.ok is False
    # "skipped" must NOT be counted as a failure.
    assert skipped_run not in failures


def test_activegraph_observability_migration_MigrationReport_failures_empty_when_no_failures() -> None:
    """Boundary/error behavior: no failed runs -> empty tuple, and the
    empty-report edge case also yields an empty tuple while being ok."""
    # All non-failed runs -> no failures, report is ok.
    clean_report = MigrationReport(
        source_url="sqlite:///src.db",
        dest_url="sqlite:///dst.db",
        runs=(_run("a", "ok"), _run("b", "skipped")),
    )
    assert clean_report.failures == ()
    assert clean_report.ok is True

    # Empty report (no runs at all) -> empty failures tuple, still ok.
    empty_report = MigrationReport(
        source_url="sqlite:///src.db",
        dest_url="sqlite:///dst.db",
        runs=(),
    )
    assert empty_report.failures == ()
    assert empty_report.ok is True

    # All runs failed -> every run is surfaced, in order, and not ok.
    failed_a = _run("a", "failed")
    failed_b = _run("b", "failed")
    all_failed_report = MigrationReport(
        source_url="sqlite:///src.db",
        dest_url="sqlite:///dst.db",
        runs=(failed_a, failed_b),
    )
    assert all_failed_report.failures == (failed_a, failed_b)
    assert all_failed_report.ok is False
