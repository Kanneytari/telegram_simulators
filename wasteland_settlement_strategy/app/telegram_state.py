from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .prototype_runtime import ManualClock, PrototypeEngine
from .scenario import bootstrap_state, settlement_scenario


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class PlayerSession:
    engine: PrototypeEngine
    selected_sector: str = "rust_belt"
    selected_residents: set[str] = field(default_factory=set)
    chat_id: int | None = None
    notified_event_count: int = 0


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[int, PlayerSession] = {}

    def _new_session(self, user_id: int) -> PlayerSession:
        engine = PrototypeEngine(
            scenario=settlement_scenario,
            state=bootstrap_state(),
            clock=ManualClock(utc_now_naive()),
            seed=user_id,
        )
        return PlayerSession(engine=engine)

    def get(self, user_id: int) -> PlayerSession:
        session = self._sessions.get(user_id)
        if session is None:
            session = self._new_session(user_id)
            self._sessions[user_id] = session
        return session

    def reset(self, user_id: int) -> PlayerSession:
        session = self._new_session(user_id)
        self._sessions[user_id] = session
        return session

    def sync(self, user_id: int) -> tuple[PlayerSession, int]:
        session = self.get(user_id)
        session.engine.clock.advance_to(utc_now_naive())
        executed = session.engine.run_due()
        return session, executed

    def all_sessions(self) -> tuple[tuple[int, PlayerSession], ...]:
        return tuple(self._sessions.items())


sessions = SessionStore()
