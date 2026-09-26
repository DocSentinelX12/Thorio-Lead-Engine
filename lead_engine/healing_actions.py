"""Checkpointed, reversible healing action execution."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from .healing_state import HealingState, HealingStateError


class HealingActionError(RuntimeError):
    pass


class HealingActionExecutor:
    def __init__(self, state: HealingState):
        self.state = state

    def execute(
        self, *, action_id: str, owner: str,
        steps: Sequence[tuple[str, Callable[[], Any]]],
        compensations: Sequence[tuple[str, Callable[[], Any]]] = (),
        now: float | None = None,
    ) -> dict[str, Any]:
        try:
            current = self.state.action(action_id)
            if current.get("owner") != owner:
                raise HealingActionError("fenced")
            if now is not None and (
                current.get("lease_expires_at") is None
                or float(current["lease_expires_at"]) <= float(now)
            ):
                raise HealingActionError("fenced")
            completed: list[str] = []
            for name, operation in steps:
                if not name.strip():
                    raise HealingActionError("checkpoint name is required")
                operation()
                completed.append(name)
                self.state.checkpoint(
                    action_id=action_id,
                    owner=owner,
                    checkpoint=name,
                    payload={"completed_steps": tuple(completed)},
                )
            return {"action_id": action_id, "state": "SUCCEEDED", "checkpoint": completed[-1] if completed else None}
        except HealingActionError:
            raise
        except Exception as exc:
            for name, operation in reversed(tuple(compensations)):
                try:
                    operation()
                    self.state.checkpoint(
                        action_id=action_id,
                        owner=owner,
                        checkpoint=f"compensated:{name}",
                        payload={"compensation": name},
                    )
                except Exception:
                    self.state.enter_degraded(
                        scope_id=self.state.action(action_id)["scope_id"],
                        reason="compensation-failed",
                        now=now,
                    )
                    return {"action_id": action_id, "state": "DEGRADED", "error": str(exc)}
            return {"action_id": action_id, "state": "ROLLED_BACK", "error": str(exc)}
