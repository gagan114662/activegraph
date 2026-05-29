"""T7 medium 003 coverage for activegraph.core.overrides.CoercedOverride.to_event_payload.

`to_event_payload` mints the D-3 fork-attestation payload from a CoercedOverride.
It is exercised here on REAL CoercedOverride objects (no mocks of the API under
test): one built directly, and one produced by the real `validate_override`
coercion path against a real Pydantic pack settings_schema. Covers the happy
path, JSON-coercion of a non-trivial typed value, and the schema-constraint
snapshot round-trip.
"""

from typing import Annotated

import pytest
from pydantic import BaseModel, Field

from activegraph.core.overrides import CoercedOverride, validate_override

pytestmark = getattr(
    pytest.mark, "activegraph.core.overrides.CoercedOverride.to_event_payload"
)


def test_activegraph_core_overrides_CoercedOverride_to_event_payload_happy_path():
    override = CoercedOverride(
        key="temperature",
        value=0.7,
        pack_name="demo_pack",
        pack_version="1.2.0",
        schema_constraint_snapshot={"type": "float", "ge": 0.0, "le": 1.0},
    )

    payload = override.to_event_payload()

    assert payload["pack"] == {"name": "demo_pack", "version": "1.2.0"}
    assert payload["key"] == "temperature"
    assert payload["value"] == 0.7
    assert payload["schema_constraint_snapshot"] == {
        "type": "float",
        "ge": 0.0,
        "le": 1.0,
    }


def test_activegraph_core_overrides_CoercedOverride_to_event_payload_from_validate_override_is_jsonable():
    # Build a CoercedOverride the real way: coerce a raw CLI string through a
    # real Pydantic settings_schema, then mint the payload.
    class _Settings(BaseModel):
        max_retries: Annotated[int, Field(ge=1, le=10)] = 3

    class _Pack:
        name = "retry_pack"
        version = "0.0.1"
        settings_schema = _Settings

    coerced = validate_override("max_retries", "5", _Pack())
    payload = coerced.to_event_payload()

    # Raw "5" was coerced to the typed int 5 and survives JSON-coercion.
    assert payload["value"] == 5
    assert isinstance(payload["value"], int)
    assert payload["pack"] == {"name": "retry_pack", "version": "0.0.1"}
    assert payload["key"] == "max_retries"
    # The constraint snapshot captured the field bounds for replay attestation.
    snapshot = payload["schema_constraint_snapshot"]
    assert snapshot["ge"] == 1
    assert snapshot["le"] == 10
