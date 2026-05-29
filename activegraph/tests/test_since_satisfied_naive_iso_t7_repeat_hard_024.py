"""T7 repeat hard 024 — docstring↔code drift in ``_since_satisfied``.

``activegraph/cli/events_tail.py::_since_satisfied`` documents:

    "Return True iff ``event_ts`` is at or after ``since``."
    "... For events whose stored timestamp is non-ISO, fall back
     to lexicographic compare ..."

The documented contract is that the function ALWAYS returns a bool: the
ordering verdict for canonical timestamps, and a lexicographic verdict for
anything that doesn't parse as ISO.

``since`` is validated tz-aware at parse time, but ``event_ts`` comes from
stored event rows. A stored ``event_ts`` that is valid ISO 8601 but *naive*
(no timezone offset) parses without raising — so the ``except ValueError``
fallback never fires — and then ``naive_datetime >= aware_datetime`` raises
``TypeError`` instead of returning a bool. The function does not honor its
documented "Return True iff ..." contract for that input; it crashes.

This is the bug: docstring promises a bool verdict (with a graceful
lexicographic fallback for non-canonical timestamps), the code raises
``TypeError`` for a naive-but-ISO ``event_ts``.
"""

from activegraph.cli.events_tail import _since_satisfied


def test_naive_iso_event_ts_returns_bool_not_typeerror():
    # since is tz-aware (as guaranteed by parse-time validation).
    since = "2026-05-15T10:00:00+00:00"
    # event_ts is valid ISO 8601 but naive (no offset) — a realistic stored
    # timestamp that is NOT the canonical Z-suffixed UTC text.
    naive_after = "2026-05-15T10:32:01"   # clock-time after `since`
    naive_before = "2026-05-15T09:00:00"  # clock-time before `since`

    # Per the docstring, the function must RETURN a bool, never raise.
    result_after = _since_satisfied(naive_after, since)
    result_before = _since_satisfied(naive_before, since)

    assert isinstance(result_after, bool)
    assert isinstance(result_before, bool)
    # And the verdict must follow "at or after": treating the naive stamp as
    # the same UTC wall-clock, 10:32:01 is after 10:00:00, 09:00:00 is before.
    assert result_after is True
    assert result_before is False
