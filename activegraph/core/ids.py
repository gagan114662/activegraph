"""ID generation. CONTRACT #1.

All IDs flow through one generator so tests can swap in a deterministic one.
v0 uses short prefixed monotonic strings; ULIDs may slot in behind this
interface in v0.5+ without changing call sites.
"""

from __future__ import annotations


class IDGen:
    """Per-graph monotonic ID generator. Not thread-safe (v0 is single-threaded)."""

    def __init__(self) -> None:
        # CONTRACT #1: objects use a global counter prefixed by type
        # (matches the README trace: task#1, task#2, claim#3 — not claim#1).
        self._object_counter = 0
        self._event_counter = 0
        self._relation_counter = 0
        self._patch_counter = 0
        self._frame_counter = 0

    def object(self, type_: str) -> str:
        self._object_counter += 1
        return f"{type_}#{self._object_counter}"

    def event(self) -> str:
        self._event_counter += 1
        return f"evt_{self._event_counter:03d}"

    def relation(self) -> str:
        self._relation_counter += 1
        return f"rel_{self._relation_counter:03d}"

    def patch(self) -> str:
        self._patch_counter += 1
        return f"patch_{self._patch_counter:03d}"

    def frame(self) -> str:
        self._frame_counter += 1
        return f"frame_{self._frame_counter:03d}"
