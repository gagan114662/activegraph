import pytest

from activegraph.observability.status import (
    BehaviorInfo,
    BudgetSnapshot,
    EventSummary,
    FrameSnapshot,
    RuntimeStatus,
    status_to_dict,
)


pytestmark = getattr(pytest.mark, "activegraph.observability.status.status_to_dict")


def test_activegraph_observability_status_status_to_dict_serializes_nested_dataclasses() -> None:
    status = RuntimeStatus(
        run_id="run-001",
        state="idle",
        queue_depth=0,
        events_processed=3,
        budget=BudgetSnapshot(
            used={"tokens": 12.0},
            limits={"tokens": 100.0},
            cost_used_usd="0.01",
            cost_limit_usd="1.00",
            exhausted_by=None,
        ),
        frame=FrameSnapshot(id="frame-1", name="Launch"),
        registered_behaviors=(
            BehaviorInfo(
                name="summarize",
                kind="function",
                subscribed_to=("object.created",),
                pattern="object.*",
                activate_after=2,
            ),
        ),
        recent_events=(
            EventSummary(
                id="evt-1",
                type="object.created",
                actor="runtime",
                timestamp="2026-05-26T00:00:00Z",
            ),
        ),
    )

    result = status_to_dict(status)

    assert result["run_id"] == "run-001"
    assert result["budget"] == {
        "used": {"tokens": 12.0},
        "limits": {"tokens": 100.0},
        "cost_used_usd": "0.01",
        "cost_limit_usd": "1.00",
        "exhausted_by": None,
    }
    assert result["frame"] == {"id": "frame-1", "name": "Launch"}
    assert result["registered_behaviors"] == [
        {
            "name": "summarize",
            "kind": "function",
            "subscribed_to": ["object.created"],
            "pattern": "object.*",
            "activate_after": 2,
        }
    ]
    assert result["recent_events"] == [
        {
            "id": "evt-1",
            "type": "object.created",
            "actor": "runtime",
            "timestamp": "2026-05-26T00:00:00Z",
        }
    ]


def test_activegraph_observability_status_status_to_dict_preserves_absent_optional_fields() -> None:
    status = RuntimeStatus(
        run_id="run-002",
        state="exhausted",
        queue_depth=5,
        events_processed=9,
        budget=BudgetSnapshot(
            used={},
            limits={"usd": None},
            cost_used_usd="0",
            cost_limit_usd=None,
            exhausted_by="usd",
        ),
        frame=None,
        registered_behaviors=(),
        recent_events=(),
    )

    result = status_to_dict(status)

    assert result["state"] == "exhausted"
    assert result["frame"] is None
    assert result["budget"]["limits"] == {"usd": None}
    assert result["budget"]["cost_limit_usd"] is None
    assert result["budget"]["exhausted_by"] == "usd"
    assert result["registered_behaviors"] == []
    assert result["recent_events"] == []
