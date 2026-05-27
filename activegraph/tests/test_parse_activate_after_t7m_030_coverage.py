import pytest

from activegraph.runtime.scheduler import InvalidActivateAfter, parse_activate_after


pytestmark = getattr(pytest.mark, "activegraph.runtime.scheduler.parse_activate_after")


def test_activegraph_runtime_scheduler_parse_activate_after_accepts_positive_int() -> None:
    assert parse_activate_after(1) == 1
    assert parse_activate_after(5) == 5
    assert parse_activate_after(42) == 42


def test_activegraph_runtime_scheduler_parse_activate_after_accepts_numeric_strings_with_units() -> None:
    assert parse_activate_after("3") == 3
    assert parse_activate_after("  7  ") == 7
    assert parse_activate_after("1 event") == 1
    assert parse_activate_after("12 events") == 12
    assert parse_activate_after("4 EVENTS") == 4


def test_activegraph_runtime_scheduler_parse_activate_after_rejects_bool_with_specific_kind() -> None:
    with pytest.raises(InvalidActivateAfter) as exc_info:
        parse_activate_after(True)
    assert exc_info.value.kind == "bool not int"
    assert exc_info.value.spec is True

    with pytest.raises(InvalidActivateAfter):
        parse_activate_after(False)


def test_activegraph_runtime_scheduler_parse_activate_after_rejects_wall_clock_units() -> None:
    for spec in ("5 seconds", "30 minutes", "2 hours", "1 day", "10 ms"):
        with pytest.raises(InvalidActivateAfter) as exc_info:
            parse_activate_after(spec)
        assert exc_info.value.kind == "wall-clock unit"
        # CONTRACT v0.7 #13 escape hatch must be cited in the hint.
        assert "event count" in exc_info.value.hint


def test_activegraph_runtime_scheduler_parse_activate_after_rejects_zero_and_negative() -> None:
    for spec in (0, -1, -10, "0", "0 events"):
        with pytest.raises(InvalidActivateAfter) as exc_info:
            parse_activate_after(spec)
        assert exc_info.value.kind == "must be >= 1"


def test_activegraph_runtime_scheduler_parse_activate_after_rejects_unparseable_strings_and_wrong_types() -> None:
    for spec in ("five", "abc", "5x", "5 cookies"):
        with pytest.raises(InvalidActivateAfter) as exc_info:
            parse_activate_after(spec)
        assert exc_info.value.kind == "unparseable string"

    with pytest.raises(InvalidActivateAfter) as exc_info:
        parse_activate_after(1.5)
    assert "type float" in exc_info.value.kind

    with pytest.raises(InvalidActivateAfter) as exc_info:
        parse_activate_after(None)
    assert "type NoneType" in exc_info.value.kind
