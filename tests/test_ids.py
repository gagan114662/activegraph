from activegraph import IDGen


def test_object_ids_are_global_monotonic_with_type_prefix():
    ids = IDGen()
    assert ids.object("task") == "task#1"
    assert ids.object("task") == "task#2"
    # Counter is global — third object is #3 even with a different type.
    assert ids.object("claim") == "claim#3"


def test_event_ids_zero_padded():
    ids = IDGen()
    assert ids.event() == "evt_001"
    assert ids.event() == "evt_002"


def test_relation_patch_frame_namespaces():
    ids = IDGen()
    assert ids.relation() == "rel_001"
    assert ids.patch() == "patch_001"
    assert ids.frame() == "frame_001"
