from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "shadow_market_simulator" / "app"


def write(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def replace_method(path: Path, class_name: str, method_name: str, replacement: str | None) -> None:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method_name:
                    lines = text.splitlines(keepends=True)
                    new = [] if replacement is None else [replacement.rstrip() + "\n"]
                    lines[child.lineno - 1 : child.end_lineno] = new
                    write(path, "".join(lines))
                    return
    if replacement is not None:
        raise RuntimeError(f"{path.name}: {class_name}.{method_name} not found")


def insert_before_method(path: Path, class_name: str, method_name: str, addition: str) -> None:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method_name:
                    lines = text.splitlines(keepends=True)
                    lines[child.lineno - 1 : child.lineno - 1] = [addition.rstrip() + "\n\n"]
                    write(path, "".join(lines))
                    return
    raise RuntimeError(f"{path.name}: insertion point {class_name}.{method_name} not found")


def clean_workflow() -> None:
    path = APP / "workflow.py"
    replace_method(path, "WorkflowSimulationEngine", "_simulate_sales", None)
    replace_method(path, "WorkflowSimulationEngine", "_create_retail_order", None)
    replace_method(
        path,
        "WorkflowSimulationEngine",
        "_simulate_management_events",
        '''    def _simulate_management_events(self, conn, player_id: int, sim_hours: float, now) -> int:\n        created = 0\n        chances = min(sim_hours, 12.0)\n        if self.rng.random() < 1 - math.exp(-0.035 * chances):\n            client = conn.execute(\n                "SELECT * FROM clients WHERE player_id=? AND shop_orders>0 ORDER BY RANDOM() LIMIT 1",\n                (player_id,),\n            ).fetchone()\n            if client:\n                percent = self.rng.choice([2, 3, 4, 5])\n                conn.execute(\n                    """INSERT INTO inbox(player_id, kind, priority, title, body, payload_json, expires_at)\n                       VALUES (?, 'discount_request', 'important', 'Просьба постоянного клиента', ?, ?, ?)""",\n                    (\n                        player_id,\n                        f"{client['alias']} просит небольшую скидку.\\n\\nРазмер: <b>{percent}%</b>\\nПричина: не хватает суммы после изменения курса.",\n                        json.dumps({"client_id": client["id"], "percent": percent}, ensure_ascii=False),\n                        iso(now + self._game_hours_to_real(player_id, 0.75)),\n                    ),\n                )\n                created += 1\n\n        created += self._check_overexposure_risk(conn, player_id, sim_hours, now)\n        return created''',
    )

    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "VALUES (?, 'employee_theft', 'urgent', 'Сотрудник пропал', ?, ?)",
        "VALUES (?, 'employee_exit', 'urgent', 'Сотрудник пропал', ?, ?)",
    )
    old_wage = '''                conn.execute(\n                    """UPDATE employees SET jobs_done=jobs_done+1, wages_accrued=wages_accrued+?,\n                           stress=MIN(100, stress+1.2), last_contact_at=? WHERE id=?""",\n                    (employee["pay_per_job"], iso(now), employee_id),\n                )\n'''
    if old_wage not in text:
        raise RuntimeError("workflow receive-time wage block not found")
    text = text.replace(old_wage, "", 1)
    text = text.replace(
        '            f"Начислено за операцию: {employee[\'pay_per_job\']:,} ₽"\n',
        '            "Оплата за работу будет начислена после передачи товара рознице."\n',
        1,
    )
    write(path, text)

    replace_method(path, "WorkflowGameService", "packaging_rules", None)
    replace_method(path, "WorkflowGameService", "adjust_packaging_rule", None)


def clean_final_workflow() -> None:
    path = APP / "workflow_final.py"
    replace_method(path, "FinalWorkflowSimulationEngine", "__init__", None)
    replace_method(path, "FinalWorkflowSimulationEngine", "_create_retail_order", None)
    replace_method(path, "FinalWorkflowGameService", "hire_candidate", None)
    replace_method(
        path,
        "FinalWorkflowGameService",
        "change_employee_role",
        '''    def change_employee_role(self, player_id: int, employee_id: int) -> str:\n        with self.db.connect() as conn:\n            employee = conn.execute(\n                "SELECT * FROM employees WHERE id=? AND player_id=? AND active=1",\n                (employee_id, player_id),\n            ).fetchone()\n            if not employee:\n                return "Сотрудник недоступен."\n            exposure = self.simulation.employee_exposure(conn, player_id, employee_id)\n            active_task = conn.execute(\n                "SELECT 1 FROM employee_tasks WHERE employee_id=? AND status='active' LIMIT 1",\n                (employee_id,),\n            ).fetchone()\n            pending = conn.execute(\n                """SELECT 1 FROM retail_allocations\n                   WHERE player_id=? AND status IN ('waiting','preparing')\n                     AND (retail_employee_id=? OR wholesale_employee_id=?) LIMIT 1""",\n                (player_id, employee_id, employee_id),\n            ).fetchone()\n            if exposure > 0 or active_task or pending:\n                return "Сначала сотрудник должен завершить текущие задачи и не иметь назначенного товара."\n            new_role = "warehouse" if employee["role"] == "courier" else "courier"\n            conn.execute("UPDATE employees SET role=? WHERE id=?", (new_role, employee_id))\n        role_title = "оптовый" if new_role == "warehouse" else "розничный"\n        return f"{employee['alias']} переведён в роль «{role_title}»."''',
    )
    text = path.read_text(encoding="utf-8")
    text = text.replace("from .runtime import ROLE_MARKET_PAY, STAFF_INBOX_KINDS\n", "")
    text = text.replace("STAFF_INBOX_KINDS.add(\"resignation_notice\")\n\n", "")
    write(path, text)


def clean_compensation() -> None:
    path = APP / "compensation.py"
    replace_method(path, "CompensationSimulationEngine", "_create_retail_order", None)
    replace_method(
        path,
        "CompensationSimulationEngine",
        "_simulate_management_events",
        '''    def _simulate_management_events(self, conn, player_id: int, sim_hours: float, now) -> int:\n        created = super()._simulate_management_events(conn, player_id, sim_hours, now)\n        conn.execute(\n            """UPDATE employees SET deposit_accrued=0\n               WHERE player_id=? AND wages_accrued=0 AND deposit_accrued<>0""",\n            (player_id,),\n        )\n        return created''',
    )
    replace_method(path, "CompensationGameService", "buy_offer_for_employee", None)
    replace_method(path, "CompensationGameService", "change_employee_role", None)
    replace_method(
        path,
        "CompensationGameService",
        "hire_candidate",
        '''    def hire_candidate(self, player_id: int, candidate_id: int) -> str:\n        with self.db.connect() as conn:\n            candidate = conn.execute(\n                "SELECT * FROM candidates WHERE id=? AND player_id=? AND status='open'",\n                (candidate_id, player_id),\n            ).fetchone()\n            if not candidate:\n                return "Кандидат уже недоступен."\n            deposit = int(candidate["deposit"])\n            cur = conn.execute(\n                """INSERT INTO employees(\n                       player_id, alias, role, deposit, has_car,\n                       reliability, attention, honesty, loyalty\n                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",\n                (\n                    player_id, candidate["alias"], candidate["role"], deposit,\n                    candidate["has_car"], candidate["reliability"], candidate["attention"],\n                    candidate["honesty"], candidate["loyalty"],\n                ),\n            )\n            employee_id = int(cur.lastrowid)\n            conn.execute(\n                "UPDATE shops SET balance=balance+? WHERE player_id=?",\n                (deposit, player_id),\n            )\n            conn.execute(\n                """INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note)\n                   VALUES (?, ?, 'deposit_in', 'employee', ?, ?)""",\n                (player_id, deposit, employee_id, f"Стартовый депозит сотрудника {candidate['alias']}"),\n            )\n            conn.execute("UPDATE candidates SET status='hired' WHERE id=?", (candidate_id,))\n        self.simulation._ensure_packaging_rules(player_id)\n        policy = self.compensation_policy(player_id, str(candidate["role"]))\n        if candidate["role"] == "courier":\n            terms = f"{policy['fixed_fee']:,} ₽ за заказ + {policy['base_rate_bps'] / 100:.1f}% с продажи"\n        else:\n            terms = (\n                f"{policy['base_rate_bps'] / 100:.1f}% от передачи + "\n                f"{policy['risk_rate_bps'] / 100:.1f}% за непокрытый риск"\n            )\n        return (\n            f"<b>{candidate['alias']} принят.</b>\\n\\n"\n            f"Условия: {terms}\\n"\n            f"В депозит из заработка: {policy['deposit_contribution_pct']}%\\n"\n            f"Стартовый депозит: {deposit:,} ₽"\n        )''',
    )

    text = path.read_text(encoding="utf-8")
    text = text.replace(
        '            conn.execute(\n                "UPDATE employees SET pay_per_job=0, deposit_contribution_pct=0 WHERE player_id=?",\n                (player_id,),\n            )\n',
        "",
    )
    write(path, text)


def clean_order_pipeline() -> None:
    trust = APP / "customer_trust.py"
    text = trust.read_text(encoding="utf-8")
    mirror = '''        # Preserve the generic client field for old risk calculations, but make the\n        # shop-specific relationship the canonical loyalty source.\n        updated = clamp(float(relationship["trust"]) + trust_delta, 0.0, 1.0)\n        conn.execute("UPDATE clients SET loyalty=? WHERE id=?", (updated, order["client_id"]))\n'''
    text = text.replace(mirror, "")
    write(trust, text)
    insert_before_method(
        trust,
        "CustomerTrustSimulationEngine",
        "_create_retail_order",
        '''    def _employee_deposit_contribution(\n        self, conn, player_id: int, employee_id: int, employee_cost: int, default_pct: int\n    ) -> int:\n        return _deposit_part(employee_cost, default_pct)''',
    )
    text = trust.read_text(encoding="utf-8")
    old = '''        deposit_part = _deposit_part(\n            employee_cost, int(policy["deposit_contribution_pct"])\n        )'''
    new = '''        deposit_part = self._employee_deposit_contribution(\n            conn,\n            player_id,\n            int(position["employee_id"]),\n            employee_cost,\n            int(policy["deposit_contribution_pct"]),\n        )'''
    if old not in text:
        raise RuntimeError("customer trust deposit calculation not found")
    write(trust, text.replace(old, new, 1))

    management = APP / "courier_management.py"
    replace_method(management, "CourierManagementSimulationEngine", "_simulate_management_events", None)
    replace_method(management, "CourierManagementSimulationEngine", "_create_retail_order", None)
    insert_before_method(
        management,
        "CourierManagementSimulationEngine",
        "_effective_pace",
        '''    def _employee_deposit_contribution(\n        self, conn, player_id: int, employee_id: int, employee_cost: int, default_pct: int\n    ) -> int:\n        management = self._management_conn(conn, employee_id)\n        employee = conn.execute(\n            "SELECT deposit, deposit_accrued FROM employees WHERE id=?",\n            (employee_id,),\n        ).fetchone()\n        if not management or not employee:\n            return _deposit_part(employee_cost, default_pct)\n\n        deposit = int(employee["deposit"])\n        pending = int(employee["deposit_accrued"])\n        target = int(management["deposit_target"])\n        if deposit + pending >= target:\n            return _deposit_part(employee_cost, default_pct)\n\n        pct = int(management["deposit_contribution_pct"])\n        desired = _deposit_part(employee_cost, pct)\n        return min(desired, max(0, target - deposit - pending))''',
    )


def remove_base_dead_sales() -> None:
    for filename, class_name, methods in [
        ("simulation.py", "SimulationEngine", ["_simulate_sales", "_create_order"]),
        ("runtime.py", "PlayerSimulationEngine", ["_create_order"]),
        ("staff_relationships.py", "StaffRelationshipSimulationEngine", ["_simulate_sales"]),
    ]:
        path = APP / filename
        for method in methods:
            replace_method(path, class_name, method, None)


def clean_comments_and_passes() -> None:
    for path in APP.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        text = text.replace("            pass\n            self._ensure_courier_profiles_conn", "            self._ensure_courier_profiles_conn")
        text = text.replace("            pass\n            self._ensure_courier_management_conn", "            self._ensure_courier_management_conn")
        text = text.replace('    """Keep legacy service messages visually consistent with the new Russian UI."""\n', "")
        write(path, text)


def main() -> None:
    clean_workflow()
    clean_final_workflow()
    clean_compensation()
    clean_order_pipeline()
    remove_base_dead_sales()
    clean_comments_and_passes()


if __name__ == "__main__":
    main()
