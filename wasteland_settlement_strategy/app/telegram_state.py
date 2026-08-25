from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .prototype_runtime import PrototypeEngine
from .scenario import create_initial_state


@dataclass
class PlayerSession:
    engine: PrototypeEngine
    selected_sector: str = "rust_belt"
    selected_residents: set[str] = field(default_factory=set)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[int, PlayerSession] = {}

    def get(self, user_id: int) -> PlayerSession:
        session = self._sessions.get(user_id)
        if session is None:
            session = PlayerSession(engine=PrototypeEngine(create_initial_state()))
            self._sessions[user_id] = session
        return session

    def reset(self, user_id: int) -> PlayerSession:
        session = PlayerSession(engine=PrototypeEngine(create_initial_state()))
        self._sessions[user_id] = session
        return session

    def advance_due(self, user_id: int) -> PlayerSession:
        session = self.get(user_id)
        now = datetime.now(timezone.utc)
        session.engine.advance_to(now)
        return session


sessions = SessionStore()
