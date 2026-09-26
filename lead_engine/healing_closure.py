"""Final healing closure gate."""

from __future__ import annotations

from typing import Any


class HealingClosureError(RuntimeError):
    pass


class HealingClosureValidator:
    def close(self, *, authoritative_verified: bool, healing_verified: bool,
              secondary_damage: bool) -> dict[str, Any]:
        if not authoritative_verified:
            raise HealingClosureError("authoritative verification is required")
        if not healing_verified:
            raise HealingClosureError("healing-specific verification is required")
        if secondary_damage:
            raise HealingClosureError("secondary damage remains unresolved")
        return {"state": "CLOSED"}
