"""Prompt assembler + view serializer.

CONTRACT v0.6 #6, #13, #20. This is the load-bearing module of v0.6:

  * Developers don't write prompts in user code. The runtime assembles
    every prompt from four locked sources, in this order:

        1. system     — frame goal, frame constraints, behavior role
                        description, output-schema reminder
        2. view       — serialized scoped graph view (objects + relations
                        + recent events)
        3. event      — the triggering event, serialized as JSON
        4. instruction — a single sentence derived from `creates=` and
                        `output_schema=`

  * The format of (2), the view serialization, is part of the public
    contract per decision #13. It is snapshot-tested. Changing it is a
    breaking change to the framework.

  * `AssembledPrompt.hash()` returns a stable SHA-256 over the
    canonical JSON of {model, system, messages, output_schema_name,
    temperature, max_tokens, top_p, deterministic}. This is the cache
    key used by the replay layer. Hash stability matters; tests
    snapshot it.

  * `behavior.build_prompt(event, graph)` is public for debugging
    (decision #20). A developer should be able to inspect the exact
    bytes that would have gone to the model, without making a call.

`prompt_template=` (str.format-style with {system}, {view}, {event},
{instruction}) is the only escape hatch — and it still receives the
same four runtime-assembled inputs. There is no raw string-concat
path in user code.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from activegraph.core.event import Event
from activegraph.core.view import View
from activegraph.frame import Frame
from activegraph.llm.types import LLMMessage


# ---------- AssembledPrompt -------------------------------------------------


@dataclass
class AssembledPrompt:
    """A fully-assembled prompt + provider-call parameters.

    Returned by `assemble_prompt(...)` and by
    `LLMBehavior.build_prompt(event, graph)`. The runtime hashes this
    to look up a cached response before deciding to call the provider.
    """

    system: str
    messages: list[LLMMessage]
    model: str
    max_tokens: int
    temperature: float
    top_p: float
    output_schema_name: Optional[str]
    output_schema_json: Optional[dict[str, Any]]
    deterministic: bool

    # Source-by-source breakdown — useful for debugging and for
    # snapshot tests that target a single section.
    sections: dict[str, str] = field(default_factory=dict)

    def to_hashable(self) -> dict[str, Any]:
        """Canonical content used for hashing. Recorded-at timestamps,
        latencies, and other run-specific data are NOT included."""

        return {
            "model": self.model,
            "system": self.system,
            "messages": [m.to_dict() for m in self.messages],
            "output_schema_name": self.output_schema_name,
            "output_schema_json": self.output_schema_json,
            "max_tokens": int(self.max_tokens),
            "temperature": float(self.temperature),
            "top_p": float(self.top_p),
            "deterministic": bool(self.deterministic),
        }

    def canonical_json(self) -> str:
        return json.dumps(
            self.to_hashable(), sort_keys=True, separators=(",", ":")
        )

    def hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


# ---------- view serialization (CONTRACT v0.6 #13 — format is locked) -------


def serialize_view(
    view: View,
    *,
    around: Optional[str] = None,
    depth: Optional[int] = None,
) -> str:
    """Render a scoped view as the prompt-ready Markdown block.

    Format is locked — snapshot-tested in `tests/test_llm_prompt.py`.
    Changing this is a breaking change to the v0.6 contract.
    """

    header_bits: list[str] = []
    if depth is not None:
        header_bits.append(f"depth={depth}")
    if around:
        header_bits.append(f"around={around}")
    header_suffix = f" ({', '.join(header_bits)})" if header_bits else ""

    lines: list[str] = [f"## Graph context{header_suffix}", ""]

    objects = view.objects()
    lines.append("### Objects")
    if not objects:
        lines.append("- (none)")
    else:
        for o in objects:
            lines.append(f"- {o.id} ({o.type}): {_canonical(o.data)}")
    lines.append("")

    relations = view.relations()
    lines.append("### Relations")
    if not relations:
        lines.append("- (none)")
    else:
        for r in relations:
            lines.append(f"- {r.source} --{r.type}--> {r.target}")
    lines.append("")

    events = view.events()
    lines.append("### Recent events")
    if not events:
        lines.append("- (none)")
    else:
        for e in events:
            summary = _event_summary(e)
            lines.append(f"- {e.id} {e.type}{summary}")

    return "\n".join(lines)


def _event_summary(e: Event) -> str:
    """One-line tail for an event in the view block.

    Stays short on purpose — the prompt should expose enough for the
    model to reason about recent activity without becoming a transcript.
    """

    p = e.payload or {}
    if e.type == "object.created":
        oid = (p.get("object") or {}).get("id", "?")
        return f" {oid}"
    if e.type == "relation.created":
        r = p.get("relation") or {}
        return f' {r.get("source", "?")} --{r.get("type", "?")}--> {r.get("target", "?")}'
    if e.type == "patch.applied":
        return f' {p.get("target", "?")}'
    if e.type == "goal.created":
        return f' "{p.get("goal", "")}"'
    return ""


def _canonical(value: Any) -> str:
    """Stable JSON for embedding inside the view block."""
    return json.dumps(value, sort_keys=True, default=str)


# ---------- system prompt ---------------------------------------------------


def build_system_prompt(
    *,
    behavior_name: str,
    description: str,
    frame: Optional[Frame],
    output_schema_name: Optional[str],
    output_schema_json: Optional[dict[str, Any]],
) -> str:
    """The system prompt is assembled — never hand-written by the user.

    Source order: frame.goal → frame.constraints → behavior.description
    → output schema reminder. If a section is absent it is omitted; the
    section headers themselves are stable so snapshot tests are tight.
    """

    blocks: list[str] = []

    blocks.append(
        f'You are an active-graph behavior named "{behavior_name}".'
    )

    if frame is not None and frame.goal:
        blocks.append(f"Mission: {frame.goal}")

    if frame is not None and frame.constraints:
        bullets = "\n".join(f"- {c}" for c in frame.constraints)
        blocks.append(f"Constraints:\n{bullets}")

    if description:
        blocks.append(f"Role: {description}")

    if output_schema_name and output_schema_json is not None:
        schema_block = json.dumps(output_schema_json, indent=2, sort_keys=True)
        blocks.append(
            f"Respond with JSON that matches the `{output_schema_name}` "
            f"schema:\n{schema_block}"
        )

    return "\n\n".join(blocks)


# ---------- user message ----------------------------------------------------


def build_user_message(
    *,
    view_block: str,
    event: Event,
    instruction: str,
) -> str:
    event_block = _serialize_event(event)
    return (
        f"{view_block}\n\n"
        f"## Triggering event\n"
        f"{event_block}\n\n"
        f"## Task\n"
        f"{instruction}"
    )


def _serialize_event(event: Event) -> str:
    # Strip volatile fields (provenance, run-specific timestamps, run_id)
    # so the prompt is content-stable across runs and forks. Without
    # this, the cache would miss on every fork because the embedded
    # object's provenance carries the parent's run_id.
    clean_payload = _strip_volatile(event.payload)
    payload_json = json.dumps(clean_payload, sort_keys=True, indent=2, default=str)
    return (
        f"- id: {event.id}\n"
        f"- type: {event.type}\n"
        f"- actor: {event.actor or '?'}\n"
        f"- payload:\n```\n{payload_json}\n```"
    )


_VOLATILE_KEYS = frozenset({"provenance", "timestamp", "run_id"})


def _strip_volatile(value: Any) -> Any:
    """Recursively drop keys whose values vary across runs/forks.

    Provenance carries `run_id` and `timestamp`; both leak into the
    embedded object payload of `object.created` events and would
    otherwise destabilize the prompt hash. Stable cache lookup
    requires content-equivalence over the parts of the prompt the
    model actually reasons about.
    """

    if isinstance(value, dict):
        return {
            k: _strip_volatile(v)
            for k, v in value.items()
            if k not in _VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [_strip_volatile(v) for v in value]
    return value


# ---------- task instruction ------------------------------------------------


def build_instruction(
    *,
    creates: list[str],
    output_schema_name: Optional[str],
) -> str:
    """One-sentence summary of what the LLM is supposed to produce.

    Auto-derived from the decorator metadata so it cannot drift from
    the runtime's expectations. If the developer is creating multiple
    object types, list them; if there is a schema, name it.
    """

    if output_schema_name and creates:
        creates_str = ", ".join(sorted(set(creates)))
        return (
            f"Return JSON matching the `{output_schema_name}` schema. "
            f"Your output will be used to create objects of type: {creates_str}."
        )
    if output_schema_name:
        return f"Return JSON matching the `{output_schema_name}` schema."
    if creates:
        creates_str = ", ".join(sorted(set(creates)))
        return (
            f"Describe what objects of type {creates_str} should be created "
            f"in response to this event."
        )
    return "Describe what should happen in response to this event."


# ---------- schema rendering ------------------------------------------------


def schema_to_json(schema: Optional[type]) -> Optional[dict[str, Any]]:
    """Serialize a Pydantic BaseModel class to a JSON schema dict.

    Returns None if `schema` is None. Falls back to a name-only shell
    if `schema` does not look like a Pydantic v2 model — that lets
    third-party schema systems plug in without us hard-depending on
    Pydantic at import time.
    """

    if schema is None:
        return None
    fn = getattr(schema, "model_json_schema", None)
    if callable(fn):
        return fn()
    return {"type": "object", "title": getattr(schema, "__name__", "Unknown")}


# ---------- top-level assembly ---------------------------------------------


def assemble_prompt(
    *,
    behavior_name: str,
    description: str,
    model: str,
    output_schema: Optional[type],
    creates: list[str],
    view: View,
    event: Event,
    frame: Optional[Frame],
    around: Optional[str],
    depth: Optional[int],
    max_tokens: int,
    temperature: float,
    top_p: float,
    deterministic: bool,
    prompt_template: Optional[str] = None,
) -> AssembledPrompt:
    """Assemble a prompt for one behavior invocation.

    Returns an `AssembledPrompt` containing the system prompt, the user
    messages, and every provider-call parameter that contributes to the
    prompt-hash cache key. Pure function over its arguments — no I/O,
    no provider calls.
    """

    schema_json = schema_to_json(output_schema)
    schema_name = (
        getattr(output_schema, "__name__", None) if output_schema else None
    )

    system = build_system_prompt(
        behavior_name=behavior_name,
        description=description,
        frame=frame,
        output_schema_name=schema_name,
        output_schema_json=schema_json,
    )

    view_block = serialize_view(view, around=around, depth=depth)
    instruction = build_instruction(
        creates=list(creates), output_schema_name=schema_name
    )

    if prompt_template is not None:
        event_block = _serialize_event(event)
        try:
            user_text = prompt_template.format(
                system=system,
                view=view_block,
                event=event_block,
                instruction=instruction,
            )
        except KeyError as e:
            raise ValueError(
                f"prompt_template references unknown placeholder {e!r}. "
                f"Allowed: {{system}}, {{view}}, {{event}}, {{instruction}}"
            ) from e
    else:
        user_text = build_user_message(
            view_block=view_block, event=event, instruction=instruction
        )

    eff_temperature = 0.0 if deterministic else float(temperature)
    eff_top_p = 1.0 if deterministic else float(top_p)

    return AssembledPrompt(
        system=system,
        messages=[LLMMessage(role="user", content=user_text)],
        model=model,
        max_tokens=int(max_tokens),
        temperature=eff_temperature,
        top_p=eff_top_p,
        output_schema_name=schema_name,
        output_schema_json=schema_json,
        deterministic=bool(deterministic),
        sections={
            "system": system,
            "view": view_block,
            "event": _serialize_event(event),
            "instruction": instruction,
            "user": user_text,
        },
    )
