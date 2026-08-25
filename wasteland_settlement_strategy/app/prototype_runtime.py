from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from .model import SettlementState


class RejectedAction(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ActionResult:
    status: str
    code: str | None = None
    duplicate: bool = False


@dataclass(frozen=True)
class ScheduledTrigger:
    at: datetime
    action: Any
    idempotency_key: str


@dataclass
class ActionSpec:
    handler: Callable[["Context", Any], None]


@dataclass
class Scenario:
    name: str
    actions: dict[type, ActionSpec]


class ManualClock:
    def __init__(self, start: datetime):
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, *, minutes: int = 0, hours: int = 0, days: int = 0) -> datetime:
        self._now += timedelta(minutes=minutes, hours=hours, days=days)
        return self._now

    def advance_to(self, moment: datetime) -> datetime:
        if moment > self._now:
            self._now = moment
        return self._now


class RandomFacade:
    def __init__(self, rng: random.Random, trace: list[dict[str, Any]]):
        self._rng = rng
        self._trace = trace

    def chance(self, label: str, probability: float) -> bool:
        probability = max(0.0, min(1.0, probability))
        value = self._rng.random()
        self._trace.append({"kind": "chance", "label": label, "p": probability, "draw": value})
        return value < probability

    def randint(self, label: str, low: int, high: int) -> int:
        value = self._rng.randint(low, high)
        self._trace.append({"kind": "randint", "label": label, "low": low, "high": high, "draw": value})
        return value


class Context:
    def __init__(
        self,
        *,
        state: SettlementState,
        clock: ManualClock,
        rng: random.Random,
    ):
        self.state = state
        self.clock = clock
        self.events: list[Any] = []
        self.triggers: list[ScheduledTrigger] = []
        self.random_trace: list[dict[str, Any]] = []
        self.random = RandomFacade(rng, self.random_trace)

    def require(self, condition: bool, code: str) -> None:
        if not condition:
            raise RejectedAction(code)

    def emit(self, event: Any) -> None:
        self.events.append(event)

    def schedule(self, action: Any, *, at: datetime, idempotency_key: str) -> None:
        self.triggers.append(ScheduledTrigger(at=at, action=action, idempotency_key=idempotency_key))


class PrototypeEngine:
    """Small executable stand-in for the planned simulation_engine API.

    Scenario handlers operate on a copied state. State, emitted events and timers are
    committed together only after a successful handler call. This keeps the draft
    close to the Engine -> Effects -> Commit model without duplicating the full engine.
    """

    def __init__(
        self,
        *,
        scenario: Scenario,
        state: SettlementState,
        clock: ManualClock,
        seed: int = 1,
    ):
        self.scenario = scenario
        self.state = state
        self.clock = clock
        self._rng = random.Random(seed)
        self._idempotency: dict[str, ActionResult] = {}
        self.event_log: list[Any] = []
        self.random_trace: list[dict[str, Any]] = []
        self._triggers: list[ScheduledTrigger] = []

    @property
    def pending_triggers(self) -> tuple[ScheduledTrigger, ...]:
        return tuple(sorted(self._triggers, key=lambda item: item.at))

    def execute(self, action: Any, *, idempotency_key: str) -> ActionResult:
        previous = self._idempotency.get(idempotency_key)
        if previous is not None:
            return ActionResult(status=previous.status, code=previous.code, duplicate=True)

        spec = self.scenario.actions.get(type(action))
        if spec is None:
            result = ActionResult(status="rejected", code="unknown_action")
            self._idempotency[idempotency_key] = result
            return result

        working_state = copy.deepcopy(self.state)
        ctx = Context(state=working_state, clock=self.clock, rng=self._rng)
        try:
            spec.handler(ctx, action)
        except RejectedAction as exc:
            result = ActionResult(status="rejected", code=exc.code)
            self._idempotency[idempotency_key] = result
            return result

        self.state = working_state
        self.event_log.extend(ctx.events)
        self.random_trace.extend(ctx.random_trace)
        self._triggers.extend(ctx.triggers)
        result = ActionResult(status="success")
        self._idempotency[idempotency_key] = result
        return result

    def run_due(self) -> int:
        executed = 0
        while True:
            due = [trigger for trigger in self._triggers if trigger.at <= self.clock.now()]
            if not due:
                return executed
            due.sort(key=lambda item: item.at)
            trigger = due[0]
            self._triggers.remove(trigger)
            self.execute(trigger.action, idempotency_key=trigger.idempotency_key)
            executed += 1
