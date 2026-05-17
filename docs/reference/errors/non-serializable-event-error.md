# NonSerializableEventError

A value in an event payload can't be JSON-encoded. The framework
refuses to silently pickle or drop it at emit time, because either
choice would corrupt the audit trail. The fix is to convert the value
to a JSON primitive before emitting.

This is the *encode-time* sibling of
[`CorruptedEventPayloadError`](corrupted-event-payload-error.md),
which fires at decode time on bytes that won't parse.

!!! note "Existing v0.5+ behavior preserved"
    This error has been in the framework since v0.5 as a plain
    `TypeError` subclass. v1.0 re-parents it as
    `NonSerializableEventError(StorageError, TypeError)` —
    multi-inheritance preserves `except TypeError` while adding
    `except ActiveGraphError` and `except StorageError` as broader
    catch options. Existing code keeps working unchanged.

## Quick fix

The error message names the offending field path and its Python type.
Convert the value to a JSON primitive at the emit site:

```python
# Pydantic model:
payload[field] = model.model_dump()

# dataclass:
import dataclasses
payload[field] = dataclasses.asdict(value)

# Custom object:
payload[field] = str(value)
```

If the type genuinely should serialize through the framework, add
an adapter clause to `_default` in `activegraph/store/serde.py`.
`Decimal` (→ string) and `datetime` (→ ISO 8601) are precedents.

## How to diagnose

The error message walks the payload to identify the first
non-serializable field:

```
What failed:
  While encoding an event payload for the store, the value at
  'nested.value' (type Custom) could not be JSON-encoded.
    underlying: object of type Custom is not JSON-serializable
```

`nested.value` is a dotted path into the payload dict; `Custom` is
the Python class. From code catching the exception:

```python
try:
    graph.emit("my.event", payload)
except NonSerializableEventError as e:
    print(e.context["path"])  # 'nested.value'
    print(e.context["type"])  # 'Custom'
```

If the path is `<root>`, the top-level payload itself isn't a dict;
if it ends with `[N]`, the offending value is a list element at
index N.

## When does this fire

At `graph.emit()`, `graph.add_object()`, `graph.patch_object()`,
and any other operation that constructs an event whose payload
passes through `encode_payload`. The encoding runs synchronously
before the event lands in the store, so the failure is at the call
site that produced the bad payload — not at some later replay time.

This is deliberate (CONTRACT v0.5 #4): the failure is locatable. A
behavior emitting a malformed payload sees the exception at its own
emit call, with a stack trace pointing into the behavior body.

## Why the framework refuses to continue

The store persists events as JSON so the audit trail is
human-inspectable. Custom Python types serialize through a strict
adapter (`Decimal` → string, `datetime` → ISO 8601, `set` → sorted
list); anything else is refused at emit time rather than silently
pickled or dropped. A silently-dropped event would corrupt the
replay contract; a pickled value would make the audit trail unreadable
to anything but a Python process.

See [`failure-model`](../../concepts/failure-model.md) for the
broader principle.

## What's related

- [`CorruptedEventPayloadError`](corrupted-event-payload-error.md) —
  the decode-time sibling. Fires when stored JSON bytes don't parse.
- `activegraph/store/serde.py` — the canonical adapter clauses. Add
  new types there if they should serialize framework-wide.
