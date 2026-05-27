import re

import pytest

from activegraph import IDGen


pytestmark = getattr(pytest.mark, "activegraph.core.ids.IDGen.run")


_CROCKFORD_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def test_activegraph_core_ids_idgen_run_returns_ulid_shaped_string() -> None:
    ids = IDGen()

    run_id = ids.run()

    assert isinstance(run_id, str)
    assert len(run_id) == 26
    assert _CROCKFORD_RE.match(run_id), run_id


def test_activegraph_core_ids_idgen_run_produces_unique_ids_across_calls() -> None:
    ids = IDGen()

    samples = {ids.run() for _ in range(50)}

    assert len(samples) == 50


def test_activegraph_core_ids_idgen_run_does_not_disturb_monotonic_counters() -> None:
    ids = IDGen()
    first_event = ids.event()
    first_object = ids.object("task")

    ids.run()
    ids.run()

    assert ids.event() == "evt_002"
    assert first_event == "evt_001"
    assert ids.object("task") == "task#2"
    assert first_object == "task#1"
