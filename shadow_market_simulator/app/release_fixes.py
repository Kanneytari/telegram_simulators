from __future__ import annotations

from collections import OrderedDict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery

from . import compensation, staff_insights


# These callbacks confirm one irreversible action and the source message is replaced
# immediately afterwards. Telegram/network retries can still deliver the same callback
# more than once before the edit reaches the client, so execute an exact callback from
# the same message only once per process.
_ONE_SHOT_CALLBACK_PREFIXES = (
    "team:allocdo:",
    "team:roleconfirm:",
    "team:upgradedo:",
)


class OneShotCallbackMiddleware(BaseMiddleware):
    """Suppress duplicate delivery of confirmation callbacks from one message."""

    def __init__(self, max_entries: int = 4096) -> None:
        self.max_entries = max(128, int(max_entries))
        self._seen: OrderedDict[tuple[int, int, str], None] = OrderedDict()

    @staticmethod
    def _is_one_shot(data: str | None) -> bool:
        value = data or ""
        return any(value.startswith(prefix) for prefix in _ONE_SHOT_CALLBACK_PREFIXES)

    async def __call__(self, handler, event, data):
        if not isinstance(event, CallbackQuery) or not self._is_one_shot(event.data):
            return await handler(event, data)

        message_id = int(event.message.message_id) if event.message else 0
        key = (int(event.from_user.id), message_id, str(event.data))
        if key in self._seen:
            try:
                await event.answer("Действие уже обработано.")
            except Exception:
                pass
            return None

        self._seen[key] = None
        self._seen.move_to_end(key)
        while len(self._seen) > self.max_entries:
            self._seen.popitem(last=False)
        return await handler(event, data)


def _install_start_copy_fix() -> None:
    current = staff_insights.StaffInsightSimulationEngine.ensure_player
    if getattr(current, "_nightshift_release_copy", False):
        return

    def ensure_player(self, player_id: int, username: str | None) -> bool:
        created = current(self, player_id, username)
        if created:
            with self.db.connect() as conn:
                conn.execute(
                    """UPDATE inbox
                       SET title='Первая смена',
                           body='Склад пуст. Начни с первой закупки в разделе Товар.'
                       WHERE player_id=? AND kind='tutorial' AND status='open'""",
                    (player_id,),
                )
        return created

    ensure_player._nightshift_release_copy = True
    staff_insights.StaffInsightSimulationEngine.ensure_player = ensure_player


def _install_compensation_draft_fix() -> None:
    current = compensation.CompensationGameService.adjust_compensation_policy
    if getattr(current, "_nightshift_release_draft", False):
        return

    ranges = {
        "courier": {
            "fixed_fee": (0, 1000, 50),
            "base_rate_bps": (100, 800, 50),
            "deposit_contribution_pct": (0, 50, 5),
        },
        "warehouse": {
            "base_rate_bps": (50, 500, 50),
            "risk_rate_bps": (0, 300, 50),
            "deposit_contribution_pct": (0, 50, 5),
        },
    }

    def adjust_compensation_policy(
        self, player_id: int, role: str, field: str, delta: int
    ) -> dict:
        if role not in ranges or field not in ranges[role]:
            return current(self, player_id, role, field, delta)

        low, high, step = ranges[role][field]
        delta = int(delta)
        if delta == 0 or delta % step != 0:
            return current(self, player_id, role, field, delta)
        if abs(delta) == step:
            return current(self, player_id, role, field, delta)

        before = self.compensation_policy(player_id, role)
        old_value = int(before[field])
        new_value = max(low, min(high, old_value + delta))
        if new_value == old_value:
            return {
                "changed": False,
                "policy": before,
                "reaction": "Условия уже на предельном значении.",
            }

        after = dict(before)
        after[field] = new_value
        old_score = max(1.0, self._policy_score(role, before))
        new_score = max(1.0, self._policy_score(role, after))
        relative = new_score / old_score - 1.0
        if relative > 0.001:
            severity = min(1.0, relative / 0.20)
            loyalty_delta = 0.008 + 0.018 * severity
            stress_delta = -(0.4 + 1.6 * severity)
            reaction = "Условия стали выгоднее для сотрудников."
        elif relative < -0.001:
            severity = min(1.0, abs(relative) / 0.20)
            loyalty_delta = -(0.010 + 0.025 * severity)
            stress_delta = 0.6 + 2.4 * severity
            reaction = "Условия стали хуже для сотрудников."
        else:
            loyalty_delta = 0.0
            stress_delta = 0.0
            reaction = "Экономический эффект изменения почти нейтрален."

        with self.db.connect() as conn:
            conn.execute(
                f"""UPDATE staff_compensation_policies
                    SET {field}=?, updated_at=CURRENT_TIMESTAMP
                    WHERE player_id=? AND role=?""",
                (new_value, player_id, role),
            )
            conn.execute(
                """UPDATE employees
                   SET loyalty=MIN(1.0, MAX(0.0, loyalty+?)),
                       stress=MIN(100.0, MAX(0.0, stress+?))
                   WHERE player_id=? AND role=? AND active=1""",
                (loyalty_delta, stress_delta, player_id, role),
            )
            conn.execute(
                """INSERT INTO compensation_policy_changes(
                       player_id, role, field, old_value, new_value,
                       loyalty_delta, stress_delta
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    player_id,
                    role,
                    field,
                    old_value,
                    new_value,
                    loyalty_delta,
                    stress_delta,
                ),
            )
        return {
            "changed": True,
            "policy": self.compensation_policy(player_id, role),
            "reaction": reaction,
        }

    adjust_compensation_policy._nightshift_release_draft = True
    compensation.CompensationGameService.adjust_compensation_policy = (
        adjust_compensation_policy
    )


def apply_release_fixes() -> None:
    """Install release-only correctness fixes without changing game mechanics."""
    _install_start_copy_fix()
    _install_compensation_draft_fix()
