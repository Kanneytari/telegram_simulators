from __future__ import annotations

import asyncio
from contextlib import suppress

from app.core.database import Database
from app.main import notification_loop


class NoopSimulation:
    def advance_all(self) -> None:
        return None


class NoopRecruitment:
    def advance_all(self) -> None:
        return None


class NoopGame:
    def process_payroll_all(self) -> None:
        return None


class NoopAnalytics:
    def log_notification(self, *args) -> None:
        return None


class ConcurrentWriteBot:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.calls = 0
        self.second_write_completed = asyncio.Event()

    async def send_message(self, player_id: int, text: str, **kwargs) -> None:
        self.calls += 1
        if self.calls != 2:
            return
        with self.db.connect() as conn:
            conn.execute("PRAGMA busy_timeout=50")
            conn.execute(
                "UPDATE shops SET last_seen_at=last_seen_at WHERE player_id=?",
                (player_id,),
            )
        self.second_write_completed.set()


async def run_notification_probe(db: Database, bot: ConcurrentWriteBot) -> int:
    task = asyncio.create_task(
        notification_loop(
            bot,
            db,
            NoopSimulation(),
            NoopGame(),
            NoopRecruitment(),
            NoopAnalytics(),
            interval=3600,
        )
    )
    try:
        await asyncio.wait_for(bot.second_write_completed.wait(), timeout=1.0)
        await asyncio.sleep(0.05)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    return bot.calls


def test_notification_loop_does_not_hold_sqlite_write_lock_across_send(tmp_path):
    db = Database(str(tmp_path / "notifications.db"))
    db.init()
    with db.connect() as conn:
        conn.execute("INSERT INTO shops(player_id, username) VALUES (1001, 'tester')")
        conn.executemany(
            """INSERT INTO inbox(player_id, kind, priority, title, body, payload_json)
               VALUES (1001, 'system', 'important', ?, 'body', '{}')""",
            [("first",), ("second",)],
        )

    bot = ConcurrentWriteBot(db)
    calls = asyncio.run(run_notification_probe(db, bot))

    with db.connect() as conn:
        notified = int(
            conn.execute(
                "SELECT COUNT(*) FROM inbox WHERE player_id=1001 AND notified_at IS NOT NULL"
            ).fetchone()[0]
        )
    assert calls == 2
    assert notified == 2
