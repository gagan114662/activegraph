"""T7 HARD repetition run 012 — docstring↔code drift regression test.

Target: ``activegraph.trace.printer._format_tag``.

DOCUMENTED behavior (trace/printer.py line 28 docstring + module docstring
lines 2-3): the bracketed tag is "left-padded to TAG_COL (or one trailing
space if longer)". The module docstring is even more explicit: "tag column
is left-aligned, padded to 26 chars; if the tag itself is longer, exactly
one space follows it."

So the contract is:
  * bracketed length  < TAG_COL  -> left-justified (padded) to exactly TAG_COL
  * bracketed length == TAG_COL  -> already fills the column, returned as-is
                                    (length TAG_COL, no extra space)
  * bracketed length  > TAG_COL  -> exactly one trailing space appended

The DRIFT: the code used ``len(bracketed) >= TAG_COL`` (line 30), so a tag
whose bracketed form is EXACTLY TAG_COL chars wrongly gets a trailing space
appended (length TAG_COL + 1), breaking the documented "padded to TAG_COL"
column alignment. The "one trailing space" rule is documented to apply only
when the tag is *longer* than TAG_COL.

This test asserts the documented behavior and FAILS against the ``>=`` code.
"""
from __future__ import annotations

from activegraph.trace.printer import TAG_COL, _format_tag


def _bracketed_of_inner_len(inner_len: int) -> str:
    """An inner tag text whose bracketed form is exactly ``inner_len + 2``."""
    return "e" * inner_len


def test_tag_shorter_than_col_is_padded_to_col():
    # bracketed len = 7 ("[short]") < TAG_COL -> padded to TAG_COL exactly.
    out = _format_tag("short")
    assert len(out) == TAG_COL
    assert out == "[short]".ljust(TAG_COL)


def test_tag_exactly_col_is_returned_as_is_no_trailing_space():
    # Construct a tag whose bracketed form is EXACTLY TAG_COL chars.
    inner = _bracketed_of_inner_len(TAG_COL - 2)
    bracketed = f"[{inner}]"
    assert len(bracketed) == TAG_COL  # precondition for this boundary case

    out = _format_tag(inner)

    # DOCUMENTED: padded to TAG_COL -> already TAG_COL, so no extra space.
    # The "one trailing space" rule applies only when the tag is *longer*.
    assert len(out) == TAG_COL, (
        f"tag exactly TAG_COL ({TAG_COL}) wide must occupy exactly the "
        f"column; got length {len(out)} ({out!r})"
    )
    assert not out.endswith(" "), (
        "a tag exactly TAG_COL wide must not get a trailing space "
        "(the documented trailing-space rule is 'if longer')"
    )
    assert out == bracketed


def test_tag_longer_than_col_gets_exactly_one_trailing_space():
    # bracketed len > TAG_COL -> exactly one trailing space (documented).
    inner = _bracketed_of_inner_len(TAG_COL)  # bracketed len = TAG_COL + 2
    bracketed = f"[{inner}]"
    assert len(bracketed) > TAG_COL  # precondition

    out = _format_tag(inner)
    assert out == bracketed + " "
    assert len(out) == len(bracketed) + 1
