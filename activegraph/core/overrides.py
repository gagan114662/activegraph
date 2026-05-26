"""Pack-setting override validation + coercion. T3 D-2 + D-4.

`validate_override(key, value, pack)` is the single seam:
  - resolves `key` against `pack.settings_schema` (a Pydantic BaseModel)
  - coerces `value` (raw string from the CLI) through the field validator
  - returns a `CoercedOverride` carrying the typed value, the pack
    identity, and a schema-constraint snapshot for replay attestation
  - raises `InvalidOverrideError` PRE-event when the value doesn't fit

Wired by the `activegraph fork --set` CLI and replay projector.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, cast

from pydantic import BaseModel, TypeAdapter, ValidationError
from pydantic_core import PydanticUndefined, to_jsonable_python


class InvalidOverrideError(ValueError):
    """Raised pre-event when `--set` fails validation. Carries enough
    context for a CLI diagnostic and for downstream catch-and-translate.
    """

    def __init__(
        self,
        message: str,
        *,
        key: str,
        value: Any,
        pack_name: str | None = None,
        schema_constraint: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.key = key
        self.value = value
        self.pack_name = pack_name
        self.schema_constraint = schema_constraint or {}


@dataclass(frozen=True)
class CoercedOverride:
    """Result of `validate_override`. The typed value plus everything
    needed to mint the D-3 full-attestation event payload.
    """

    key: str
    value: Any  # Pydantic-coerced typed value (float, int, bool, str, ...)
    pack_name: str
    pack_version: str
    schema_constraint_snapshot: dict[str, Any]

    def to_event_payload(self: "CoercedOverride") -> dict[str, Any]:
        """Return the override payload used in fork attestation events.

        Returns:
            A JSON-compatible payload containing pack identity, override key,
            coerced value, and the schema constraint snapshot.
        """
        value = to_jsonable_python(self.value)
        snapshot = to_jsonable_python(self.schema_constraint_snapshot)
        return {
            "pack": {"name": self.pack_name, "version": self.pack_version},
            "key": self.key,
            "value": value,
            "schema_constraint_snapshot": dict(snapshot),
        }


def _field_constraint_snapshot(schema: type[BaseModel], key: str) -> dict[str, Any]:
    """Best-effort snapshot of a field's type + constraint metadata.

    Captured at fork time so replay is self-sufficient against pack drift
    (D-3 §"schema_constraint_snapshot").
    """
    field = schema.model_fields[key]
    snap: dict[str, Any] = {}
    anno = field.annotation
    snap["type"] = getattr(anno, "__name__", str(anno))
    for attr in ("ge", "gt", "le", "lt", "min_length", "max_length", "pattern"):
        for src in field.metadata or ():
            v = getattr(src, attr, None)
            if v is not None:
                snap[attr] = v
    if field.default is not PydanticUndefined:
        try:
            snap["default"] = field.default
        except Exception:
            pass
    return snap


def validate_override(key: str, value: Any, pack: Any) -> CoercedOverride:
    """Validate + coerce a single `<key>=<value>` override against a pack.

    Per D-2 / D-4:
      - `key` must be a field on `pack.settings_schema`
      - `value` (raw string from the CLI) is coerced through Pydantic
      - on failure, raises `InvalidOverrideError` BEFORE any event mint
    """
    schema = getattr(pack, "settings_schema", None)
    pack_name = getattr(pack, "name", None) or "?"
    pack_version = getattr(pack, "version", "?")

    if schema is None or not (isinstance(schema, type) and issubclass(schema, BaseModel)):
        raise InvalidOverrideError(
            f"pack {pack_name!r} has no Pydantic settings_schema; "
            f"cannot validate --set {key}={value!r}",
            key=key,
            value=value,
            pack_name=pack_name,
        )
    schema_model = cast(type[BaseModel], schema)

    if key not in schema_model.model_fields:
        known = ", ".join(sorted(schema_model.model_fields.keys())) or "(none)"
        raise InvalidOverrideError(
            f"unknown key {key!r} for pack {pack_name!r}; "
            f"known keys: {known}",
            key=key,
            value=value,
            pack_name=pack_name,
        )

    constraint = _field_constraint_snapshot(schema_model, key)
    try:
        field = schema_model.model_fields[key]
        annotation = field.annotation
        if field.metadata:
            annotation = Annotated[annotation, *field.metadata]
        typed_value = TypeAdapter(annotation).validate_python(value)
    except ValidationError as exc:
        raise InvalidOverrideError(
            f"value {value!r} failed validation for {pack_name}.{key}: {exc}",
            key=key,
            value=value,
            pack_name=pack_name,
            schema_constraint=constraint,
        ) from exc

    return CoercedOverride(
        key=key,
        value=typed_value,
        pack_name=pack_name,
        pack_version=pack_version,
        schema_constraint_snapshot=constraint,
    )


__all__ = [
    "CoercedOverride",
    "InvalidOverrideError",
    "validate_override",
]
