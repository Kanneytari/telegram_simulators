from __future__ import annotations

from . import compensation
from .bot.middleware import OneShotCallbackMiddleware


# Compatibility export while the last release correctness overlay is being
# absorbed by its canonical feature module.
__all__ = ["OneShotCallbackMiddleware", "apply_release_fixes"]


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
    """Install the last release correctness overlay during architecture migration."""
    _install_compensation_draft_fix()
