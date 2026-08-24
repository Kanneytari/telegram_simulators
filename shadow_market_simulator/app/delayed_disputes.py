from __future__ import annotations

import math
from datetime import timedelta

from .procurement_market import ProcurementMarketGameService, ProcurementMarketSimulationEngine
from .simulation import parse_dt, utcnow


def precise_iso(dt) -> str:
    """Serialize short game timers without losing sub-second precision."""
    return dt.isoformat(timespec="microseconds")


class DelayedDisputeSimulationEngine(ProcurementMarketSimulationEngine):
    """Adds persistent game-time delays for employee dispute explanations."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    def materialize_due_replies(self, player_id: int, now=None) -> int:
        now = now or utcnow()
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT id FROM disputes
                   WHERE player_id=? AND status='open'
                     AND courier_reply IS NULL
                     AND courier_reply_pending IS NOT NULL
                     AND courier_reply_due_at IS NOT NULL
                     AND courier_reply_due_at<=?""",
                (player_id, precise_iso(now)),
            ).fetchall()
            for row in rows:
                conn.execute(
                    """UPDATE disputes
                       SET courier_reply=courier_reply_pending,
                           courier_reply_pending=NULL,
                           courier_reply_due_at=NULL
                       WHERE id=?""",
                    (row["id"],),
                )
            return len(rows)

    def advance(self, player_id: int, now=None):
        now = now or utcnow()
        result = super().advance(player_id, now)
        self.materialize_due_replies(player_id, now)
        return result

    def rescale_existing_timers(self, player_id: int, old_speed: float, new_speed: float, now=None) -> None:
        now = now or utcnow()
        self.materialize_due_replies(player_id, now)
        super().rescale_existing_timers(player_id, old_speed, new_speed, now)
        old_speed = max(0.1, float(old_speed))
        new_speed = max(0.1, float(new_speed))
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT id, courier_reply_due_at FROM disputes
                   WHERE player_id=? AND status='open'
                     AND courier_reply IS NULL
                     AND courier_reply_pending IS NOT NULL
                     AND courier_reply_due_at IS NOT NULL""",
                (player_id,),
            ).fetchall()
            for row in rows:
                target = parse_dt(row["courier_reply_due_at"])
                remaining_real = max(0.0, (target - now).total_seconds())
                remaining_game = remaining_real * old_speed
                due = now + timedelta(seconds=remaining_game / new_speed)
                conn.execute(
                    "UPDATE disputes SET courier_reply_due_at=? WHERE id=?",
                    (precise_iso(due), row["id"]),
                )

    def fast_forward_timers(self, player_id: int, game_hours: float) -> None:
        super().fast_forward_timers(player_id, game_hours)
        speed = max(0.1, float(self.effective_speed(player_id)))
        shift = timedelta(hours=max(0.0, float(game_hours)) / speed)
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT id, courier_reply_due_at FROM disputes
                   WHERE player_id=? AND status='open'
                     AND courier_reply IS NULL
                     AND courier_reply_pending IS NOT NULL
                     AND courier_reply_due_at IS NOT NULL""",
                (player_id,),
            ).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE disputes SET courier_reply_due_at=? WHERE id=?",
                    (precise_iso(parse_dt(row["courier_reply_due_at"]) - shift), row["id"]),
                )
        self.materialize_due_replies(player_id)


class DelayedDisputeGameService(ProcurementMarketGameService):
    """Schedules employee explanations instead of returning them immediately."""

    @staticmethod
    def _format_game_minutes(minutes: int) -> str:
        minutes = max(1, int(minutes))
        if minutes < 60:
            return f"{minutes} игровых мин."
        hours, rest = divmod(minutes, 60)
        if rest == 0:
            return f"{hours} игров. ч"
        return f"{hours} ч {rest} игровых мин."

    def _pending_eta(self, player_id: int, due_at: str) -> str:
        remaining_real_seconds = max(0.0, (parse_dt(due_at) - utcnow()).total_seconds())
        speed = max(0.1, float(self.simulation.effective_speed(player_id)))
        remaining_game_minutes = max(1, int(math.ceil(remaining_real_seconds * speed / 60.0)))
        return self._format_game_minutes(remaining_game_minutes)

    def _generate_employee_reply(self, row) -> str:
        cause = row["true_cause"]
        accurate = self.rng.random() < (float(row["honesty"]) * 0.65 + float(row["attention"]) * 0.25)
        if accurate:
            replies = {
                "CLIENT_FRAUD": "Уверен, что всё оформил штатно. Перепроверил свою запись - явной ошибки не вижу.",
                "EMPLOYEE_ERROR": "Перепроверил. Похоже, я действительно мог перепутать данные заказа.",
                "DESCRIPTION_ERROR": "Описание получилось слабым. Тут мой косяк, надо было оформить понятнее.",
                "QUALITY_COMPLAINT": "По исполнению заказа ошибок не вижу. Возможно, вопрос к самой партии.",
                "CLIENT_ERROR": "С моей стороны запись выглядит нормально. Возможно, клиент неправильно понял описание.",
            }
            return replies[cause]
        return self.rng.choice([
            "По памяти всё было нормально. Точно сказать уже не могу.",
            "Перепроверил свои записи - ничего очевидного не нашёл.",
            "Есть сомнение в описании, но уверенности нет.",
        ])

    def ask_employee_about_dispute(self, player_id: int, dispute_id: int) -> str:
        now = utcnow()
        self.simulation.materialize_due_replies(player_id, now)
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT d.*, e.alias, e.honesty, e.attention
                   FROM disputes d
                   JOIN orders o ON o.id=d.order_id
                   JOIN employees e ON e.id=o.employee_id
                   WHERE d.id=? AND d.player_id=?""",
                (dispute_id, player_id),
            ).fetchone()
            if not row or row["status"] != "open":
                return "Диспут уже закрыт."
            if row["courier_reply"]:
                return "Пояснение уже получено."
            if row["courier_reply_pending"] and row["courier_reply_due_at"]:
                return f"Пояснение уже запрошено. Осталось примерно {self._pending_eta(player_id, row['courier_reply_due_at'])}."

            delay_game_minutes = self.rng.randint(5, 120)
            speed = max(0.1, float(self.simulation.effective_speed(player_id)))
            due = now + timedelta(minutes=delay_game_minutes / speed)
            reply = self._generate_employee_reply(row)
            conn.execute(
                """UPDATE disputes
                   SET courier_reply_pending=?, courier_reply_due_at=?
                   WHERE id=? AND player_id=?""",
                (reply, precise_iso(due), dispute_id, player_id),
            )
            return f"Запрос отправлен. Ответ ожидается примерно через {self._format_game_minutes(delay_game_minutes)}."

    def dispute_details(self, player_id: int, dispute_id: int) -> str | None:
        self.simulation.materialize_due_replies(player_id)
        text = super().dispute_details(player_id, dispute_id)
        if not text:
            return None
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT courier_reply, courier_reply_pending, courier_reply_due_at
                   FROM disputes WHERE id=? AND player_id=?""",
                (dispute_id, player_id),
            ).fetchone()
        if row and not row["courier_reply"] and row["courier_reply_pending"] and row["courier_reply_due_at"]:
            text += (
                "\n\n<b>Ответ сотрудника</b>\n"
                f"Пояснение запрошено · осталось примерно {self._pending_eta(player_id, row['courier_reply_due_at'])}."
            )
        return text
