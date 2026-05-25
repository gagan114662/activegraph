"""Event records. CONTRACT #3: append-only, never modified.

Events are dataclasses, frozen at the Python level. Their `payload` dict is
not deeply frozen — by convention nothing mutates it after `emit`. The runtime
treats the event log as the source of truth (CONTRACT #2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class Event:
    id: str
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    actor: Optional[str] = None
    frame_id: Optional[str] = None
    caused_by: Optional[str] = None
    timestamp: str = ""

    def to_dict(self: "Event") -> dict[str, Any]:
        """Return this event as a serializable dictionary.

        Args:
            self: Event instance to serialize.

        Returns:
            A dictionary containing the event identity, type, payload, actor,
            frame, causal parent, and timestamp fields.
        """
        return {
            "id": self.id,
            "type": self.type,
            "payload": self.payload,
            "actor": self.actor,
            "frame_id": self.frame_id,
            "caused_by": self.caused_by,
            "timestamp": self.timestamp,
        }
