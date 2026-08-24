from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "shadow_market_simulator" / "app"
TESTS = ROOT / "shadow_market_simulator" / "tests"


def write(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def method_span(path: Path, class_name: str, method_name: str) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method_name:
                    return child.lineno - 1, child.end_lineno
    raise RuntimeError(f"{path.name}: {class_name}.{method_name} not found")


def replace_method(path: Path, class_name: str, method_name: str, source: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    start, end = method_span(path, class_name, method_name)
    lines[start:end] = source.strip("\n").splitlines()
    write(path, "\n".join(lines))


def remove_method(path: Path, class_name: str, method_name: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    start, end = method_span(path, class_name, method_name)
    while start > 0 and not lines[start - 1].strip():
        start -= 1
    lines[start:end] = []
    write(path, "\n".join(lines))


def clean_simulation() -> None:
    path = APP / "simulation.py"
    text = path.read_text(encoding="utf-8")
    text = re.sub(
        r"PRODUCTS = \(.*?\n\)\n\nSUPPLIERS =",
        '''PRODUCTS = (\n    (1, "AMPHETAMINE", "Амфетамин", 6000, 18.0, 0.95),\n    (2, "MDMA", "MDMA", 8000, 10.0, 1.10),\n    (3, "COCAINE", "Кокаин", 11000, 6.0, 0.90),\n    (4, "MEPHEDRONE", "Мефедрон", 7000, 15.0, 1.00),\n    (5, "KETAMINE", "Кетамин", 7500, 9.0, 1.15),\n    (6, "LSD", "LSD", 9000, 7.0, 0.85),\n)\n\nSUPPLIERS =''',
        text,
        count=1,
        flags=re.S,
    )
    text = re.sub(r'^ALIASES = .*?\n', '', text, count=1, flags=re.M)
    text = text.replace("            self._maybe_refresh_candidate(conn, player_id, now)\n", "")
    write(path, text)

    replace_method(
        path,
        "SimulationEngine",
        "ensure_player",
        r'''    def ensure_player(self, player_id: int, username: str | None) -> bool:
        self.seed_catalog()
        now = utcnow()
        with self.db.connect() as conn:
            exists = conn.execute("SELECT 1 FROM shops WHERE player_id=?", (player_id,)).fetchone()
            if exists:
                conn.execute(
                    "UPDATE shops SET username=?, last_seen_at=? WHERE player_id=?",
                    (username, iso(now), player_id),
                )
                return False

            conn.execute(
                "INSERT INTO shops(player_id, username, last_simulated_at) VALUES (?, ?, ?)",
                (player_id, username, iso(now)),
            )
            conn.execute("INSERT INTO settings(player_id) VALUES (?)", (player_id,))

            employees = [
                ("Крот", "courier", 35_000, 0, 0.91, 0.88, 0.90, 0.72, 14.0),
                ("Сова", "courier", 60_000, 1, 0.84, 0.94, 0.86, 0.81, 8.0),
            ]
            for row in employees:
                conn.execute(
                    """INSERT INTO employees(
                           player_id, alias, role, deposit, has_car,
                           reliability, attention, honesty, loyalty, stress
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (player_id, *row),
                )

            for index in range(24):
                conn.execute(
                    """INSERT INTO clients(
                           player_id, alias, account_age_days, marketplace_orders,
                           fraud_propensity, patience, review_tendency
                       ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        player_id,
                        f"{self.rng.choice(CLIENT_ALIASES)}_{index + 1}",
                        self.rng.randint(12, 1500),
                        self.rng.randint(1, 180),
                        self.rng.uniform(0.01, 0.18),
                        self.rng.uniform(0.35, 0.95),
                        self.rng.uniform(0.25, 0.85),
                    ),
                )

            for product_id, _, _, base_price, _, _ in PRODUCTS:
                for pack_size, multiplier in ((1, 1.05), (2, 1.95), (5, 4.55)):
                    price = int(round(base_price * multiplier / 100.0) * 100)
                    conn.execute(
                        "INSERT INTO listings(player_id, product_id, pack_size, price) VALUES (?, ?, ?, ?)",
                        (player_id, product_id, pack_size, price),
                    )

            starter_batches = [
                (1, 1, 80, 80, 3000, 84.0),
                (3, 2, 45, 45, 3900, 79.0),
                (1, 3, 25, 25, 5200, 90.0),
            ]
            for supplier_id, product_id, qty, remaining, unit_cost, quality in starter_batches:
                conn.execute(
                    """INSERT INTO batches(
                           player_id, supplier_id, product_id, quantity, remaining, unit_cost, quality
                       ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (player_id, supplier_id, product_id, qty, remaining, unit_cost, quality),
                )

            conn.execute(
                "INSERT INTO ledger(player_id, amount, kind, note) VALUES (?, 150000, 'capital', 'Стартовый капитал')",
                (player_id,),
            )
            self._create_offer(conn, player_id, now)
            conn.execute(
                """INSERT INTO inbox(player_id, kind, priority, title, body, payload_json, expires_at)
                   VALUES (?, 'tutorial', 'normal', 'Смена началась',
                   'Магазин работает сам по себе. Продажи, обращения и проблемы будут возникать даже когда ты офлайн. Начни с разделов «Входящие», «Команда» и «Закупки».', '{}', ?)""",
                (player_id, iso(now + timedelta(hours=12))),
            )
            return True''',
    )
    replace_method(
        path,
        "SimulationEngine",
        "_simulate_management_events",
        r'''    def _simulate_management_events(self, conn, player_id: int, sim_hours: float, now: datetime) -> int:
        return 0''',
    )
    for name in ("_maybe_refresh_candidate", "_create_candidate"):
        try:
            remove_method(path, "SimulationEngine", name)
        except RuntimeError:
            pass


def clean_runtime() -> None:
    path = APP / "runtime.py"
    write(
        path,
        r'''from __future__ import annotations

from .simulation import SimulationEngine, TickResult, iso, parse_dt, utcnow


class PlayerSimulationEngine(SimulationEngine):
    def player_multiplier(self, player_id: int) -> float:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT time_multiplier FROM settings WHERE player_id=?",
                (player_id,),
            ).fetchone()
        return max(0.1, float(row[0])) if row else 1.0

    def effective_speed(self, player_id: int) -> float:
        return max(0.1, float(self.speed) * self.player_multiplier(player_id))

    def advance(self, player_id: int, now=None) -> TickResult:
        now = now or utcnow()
        with self.db.connect() as conn:
            shop = conn.execute("SELECT * FROM shops WHERE player_id=?", (player_id,)).fetchone()
            if not shop:
                return TickResult()
            last = parse_dt(shop["last_simulated_at"])
            real_hours = max(0.0, (now - last).total_seconds() / 3600.0)
            sim_hours = min(real_hours * self.effective_speed(player_id), 72.0)
            if sim_hours < 0.015:
                return TickResult()
            orders, disputes = self._simulate_sales(conn, player_id, shop, sim_hours, now)
            messages = self._simulate_management_events(conn, player_id, sim_hours, now)
            self._reactivate_employees(conn, player_id, now)
            self._expire_items(conn, player_id, now)
            self._maybe_refresh_offer(conn, player_id, now)
            conn.execute(
                "UPDATE shops SET last_simulated_at=?, last_seen_at=? WHERE player_id=?",
                (iso(now), iso(now), player_id),
            )
            return TickResult(orders, disputes, messages)
''',
    )


def clean_nightshift() -> None:
    path = APP / "nightshift.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace("import json\n", "")
    text = text.replace("from .game import ROLE_NAMES\n", "")
    text = text.replace("from .runtime import PlayerSimulationEngine, ROLE_MARKET_PAY\n", "from .runtime import PlayerSimulationEngine\n")
    text = re.sub(r'ROLE_NAMES\["warehouse"\].*?STARTER_UNIT_COSTS = \{.*?\}\n\n\n', '', text, count=1, flags=re.S)
    write(path, text)
    remove_method(path, "NightshiftSimulationEngine", "seed_catalog")
    replace_method(
        path,
        "NightshiftSimulationEngine",
        "ensure_player",
        r'''    def ensure_player(self, player_id: int, username: str | None) -> bool:
        created = super().ensure_player(player_id, username)
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE settings SET last_payroll_at=COALESCE(last_payroll_at, ?) WHERE player_id=?",
                (iso(utcnow()), player_id),
            )
        return created''',
    )
    remove_method(path, "NightshiftSimulationEngine", "_simulate_management_events")


def clean_game_service() -> None:
    path = APP / "game.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace("import random\nfrom datetime import timedelta\n", "import random\n")
    text = text.replace('    "warehouse": "Склад",', '    "warehouse": "Оптовый сотрудник",')
    write(path, text)

    replace_method(
        path,
        "GameService",
        "dashboard",
        r'''    def dashboard(self, player_id: int) -> str:
        self.simulation.advance(player_id)
        with self.db.connect() as conn:
            shop = conn.execute("SELECT * FROM shops WHERE player_id=?", (player_id,)).fetchone()
            deposits = int(conn.execute(
                "SELECT COALESCE(SUM(deposit),0) FROM employees WHERE player_id=? AND active=1",
                (player_id,),
            ).fetchone()[0])
            stock_cost = int(conn.execute(
                "SELECT COALESCE(SUM(remaining*unit_cost),0) FROM batches WHERE player_id=? AND status='warehouse'",
                (player_id,),
            ).fetchone()[0])
            stock_units = int(conn.execute(
                "SELECT COALESCE(SUM(remaining),0) FROM batches WHERE player_id=? AND status='warehouse'",
                (player_id,),
            ).fetchone()[0])
            open_inbox = int(conn.execute(
                "SELECT COUNT(*) FROM inbox WHERE player_id=? AND status='open'", (player_id,)
            ).fetchone()[0])
            urgent = int(conn.execute(
                "SELECT COUNT(*) FROM inbox WHERE player_id=? AND status='open' AND priority IN ('important','urgent')",
                (player_id,),
            ).fetchone()[0])
            employees = int(conn.execute(
                "SELECT COUNT(*) FROM employees WHERE player_id=? AND active=1", (player_id,)
            ).fetchone()[0])
            trust = conn.execute(
                "SELECT trust_score FROM shop_trust_state WHERE player_id=?", (player_id,)
            ).fetchone()
        free_cash = int(shop["balance"]) - deposits - int(shop["reserve_target"])
        trust_score = float(trust["trust_score"]) if trust else 55.0
        return (
            f"<b>{shop['name']}</b>\n\n"
            f"Баланс: <b>{shop['balance']:,} ₽</b>\n"
            f"Свободные деньги: <b>{free_cash:,} ₽</b>\n"
            f"Товарный остаток: {stock_units} ед. / ~{stock_cost:,} ₽ по себестоимости\n"
            f"Доверие: <b>{trust_score:.0f}/100</b>\n"
            f"Сотрудников: {employees}\n"
            f"Открытых сообщений: {open_inbox}"
            + (f"\nТребуют внимания: <b>{urgent}</b>" if urgent else "")
        )''',
    )

    replace_method(
        path,
        "GameService",
        "resolve_dispute",
        r'''    def resolve_dispute(self, player_id: int, dispute_id: int, decision: str) -> str:
        if decision not in {"refund", "partial", "reject"}:
            raise ValueError("Unsupported dispute decision")
        now = utcnow()
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT d.*, o.*, c.id cid, e.id eid
                   FROM disputes d JOIN orders o ON o.id=d.order_id
                   JOIN clients c ON c.id=o.client_id JOIN employees e ON e.id=o.employee_id
                   WHERE d.id=? AND d.player_id=?""",
                (dispute_id, player_id),
            ).fetchone()
            if not row or row["status"] != "open":
                return "Этот диспут уже закрыт."
            refund = int(row["revenue"]) if decision == "refund" else int(row["revenue"] * 0.5) if decision == "partial" else 0
            if refund:
                conn.execute(
                    "UPDATE shops SET balance=balance-?, total_profit=total_profit-? WHERE player_id=?",
                    (refund, refund, player_id),
                )
                conn.execute(
                    "INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note) VALUES (?, ?, 'refund', 'order', ?, ?)",
                    (player_id, -refund, row["order_id"], f"Решение по диспуту #{dispute_id}"),
                )
            good = self._decision_quality(row["true_cause"], decision)
            if good > 0 and decision != "reject":
                conn.execute("UPDATE clients SET disputes_won=disputes_won+1 WHERE id=?", (row["cid"],))
            if row["true_cause"] in {"EMPLOYEE_ERROR", "DESCRIPTION_ERROR"}:
                if decision == "reject":
                    conn.execute("UPDATE employees SET loyalty=MIN(1.0, loyalty+0.01) WHERE id=?", (row["eid"],))
                else:
                    conn.execute("UPDATE employees SET stress=MIN(100, stress+2.5) WHERE id=?", (row["eid"],))
            conn.execute(
                "UPDATE disputes SET status='resolved', decision=?, resolved_at=? WHERE id=?",
                (decision, iso(now), dispute_id),
            )
            conn.execute("UPDATE orders SET status='completed' WHERE id=?", (row["order_id"],))
            conn.execute(
                "UPDATE inbox SET status='closed' WHERE player_id=? AND kind='dispute' AND json_extract(payload_json, '$.dispute_id')=?",
                (player_id, dispute_id),
            )
        quality_text = "Решение выглядит удачным." if good > 0 else "Решение может иметь неприятные последствия." if good < 0 else "Ситуация осталась неоднозначной."
        return f"Диспут закрыт. Компенсация: {refund:,} ₽. {quality_text}"''',
    )

    replace_method(
        path,
        "GameService",
        "handle_inbox_action",
        r'''    def handle_inbox_action(self, player_id: int, item_id: int, action: str) -> str:
        with self.db.connect() as conn:
            item = conn.execute(
                "SELECT * FROM inbox WHERE id=? AND player_id=? AND status='open'",
                (item_id, player_id),
            ).fetchone()
            if not item:
                return "Сообщение уже неактуально."
            if item["kind"] == "discount_request":
                payload = json.loads(item["payload_json"] or "{}")
                percent = int(payload.get("percent", 0))
                text = f"Скидка {percent}% согласована." if action == "approve" else "Скидка отклонена."
            else:
                text = "Сообщение закрыто."
            conn.execute("UPDATE inbox SET status='closed' WHERE id=?", (item_id,))
        return text''',
    )

    for name in ("employee_details", "candidates", "recruit", "hire_candidate", "offers", "analytics"):
        try:
            remove_method(path, "GameService", name)
        except RuntimeError:
            pass


def write_dispute_payments() -> None:
    services = APP / "services.py"
    if services.exists():
        services.unlink()
    write(
        APP / "dispute_payments.py",
        r'''from __future__ import annotations

from .game import GameService
from .simulation import iso, utcnow


class DisputePaymentGameService(GameService):
    def dispute_payment_context(self, player_id: int, dispute_id: int, decision: str) -> dict | None:
        if decision not in {"refund", "partial"}:
            return None
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT d.id dispute_id, d.status, o.id order_id, o.revenue,
                          e.id employee_id, e.alias employee_alias, e.deposit,
                          s.balance, s.reserve_target
                   FROM disputes d
                   JOIN orders o ON o.id=d.order_id
                   JOIN employees e ON e.id=o.employee_id
                   JOIN shops s ON s.player_id=d.player_id
                   WHERE d.id=? AND d.player_id=?""",
                (dispute_id, player_id),
            ).fetchone()
        if not row or row["status"] != "open":
            return None
        amount = int(row["revenue"]) if decision == "refund" else int(row["revenue"] * 0.5)
        return {
            "dispute_id": dispute_id,
            "order_id": int(row["order_id"]),
            "amount": amount,
            "employee_id": int(row["employee_id"]),
            "employee_alias": row["employee_alias"],
            "employee_deposit": int(row["deposit"]),
            "shop_balance": int(row["balance"]),
            "shop_reserve": int(row["reserve_target"]),
        }

    def resolve_dispute_with_source(self, player_id: int, dispute_id: int, decision: str, source: str) -> str:
        if decision not in {"refund", "partial", "reject"}:
            raise ValueError("Unsupported dispute decision")
        if source not in {"shop", "employee", "none"}:
            raise ValueError("Unsupported compensation source")
        if decision == "reject":
            result = super().resolve_dispute(player_id, dispute_id, "reject")
            with self.db.connect() as conn:
                conn.execute(
                    "UPDATE disputes SET refund_amount=0, refund_source='none', refund_employee_id=NULL WHERE id=? AND player_id=?",
                    (dispute_id, player_id),
                )
            return result

        context = self.dispute_payment_context(player_id, dispute_id, decision)
        if not context:
            return "Этот диспут уже закрыт."
        refund = int(context["amount"])
        if source == "shop":
            if int(context["shop_balance"]) < refund:
                return f"На счёте магазина недостаточно денег.\n\nНужно: {refund:,} ₽\nДоступно: {context['shop_balance']:,} ₽"
            result = super().resolve_dispute(player_id, dispute_id, decision)
            with self.db.connect() as conn:
                conn.execute(
                    "UPDATE disputes SET refund_amount=?, refund_source='shop', refund_employee_id=NULL WHERE id=? AND player_id=?",
                    (refund, dispute_id, player_id),
                )
            return f"{result}\nИсточник: счёт магазина."

        if int(context["employee_deposit"]) < refund:
            return f"Недостаточно средств в депозите сотрудника.\n\nНужно: {refund:,} ₽\nДоступно: {context['employee_deposit']:,} ₽"

        now = utcnow()
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT d.*, o.*, e.id eid, e.alias employee_alias, e.deposit
                   FROM disputes d JOIN orders o ON o.id=d.order_id
                   JOIN employees e ON e.id=o.employee_id
                   WHERE d.id=? AND d.player_id=?""",
                (dispute_id, player_id),
            ).fetchone()
            if not row or row["status"] != "open":
                return "Этот диспут уже закрыт."
            if int(row["deposit"]) < refund:
                return "Депозит сотрудника уже недостаточен для этой компенсации."
            conn.execute(
                "UPDATE employees SET deposit=deposit-?, losses=losses+?, stress=MIN(100, stress+2.5) WHERE id=?",
                (refund, refund, row["eid"]),
            )
            conn.execute("UPDATE shops SET balance=balance-? WHERE player_id=?", (refund, player_id))
            conn.execute(
                """INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note)
                   VALUES (?, ?, 'refund_employee_deposit', 'employee', ?, ?)""",
                (player_id, -refund, row["eid"], f"Компенсация по диспуту #{dispute_id} из депозита {row['employee_alias']}"),
            )
            good = self._decision_quality(row["true_cause"], decision)
            conn.execute(
                """UPDATE disputes
                   SET status='resolved', decision=?, refund_amount=?, refund_source='employee',
                       refund_employee_id=?, resolved_at=? WHERE id=?""",
                (decision, refund, row["eid"], iso(now), dispute_id),
            )
            conn.execute("UPDATE orders SET status='completed' WHERE id=?", (row["order_id"],))
            conn.execute(
                "UPDATE inbox SET status='closed' WHERE player_id=? AND kind='dispute' AND json_extract(payload_json, '$.dispute_id')=?",
                (player_id, dispute_id),
            )
        quality_text = "Решение выглядит удачным." if good > 0 else "Решение может иметь неприятные последствия." if good < 0 else "Ситуация осталась неоднозначной."
        return f"Диспут закрыт. Компенсация: {refund:,} ₽.\nИсточник: депозит {context['employee_alias']}.\n\n{quality_text}"
''',
    )


def clean_operations() -> None:
    path = APP / "operations.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace("from .services import FinalGameService\n", "from .dispute_payments import DisputePaymentGameService\n")
    text = text.replace("from .simulation import clamp, iso, utcnow\n", "")
    text = text.replace("class OperationsGameService(FinalGameService):", "class OperationsGameService(DisputePaymentGameService):")
    write(path, text)
    replace_method(
        path,
        "OperationsSimulationEngine",
        "ensure_player",
        r'''    def ensure_player(self, player_id: int, username: str | None) -> bool:
        created = super().ensure_player(player_id, username)
        if not created:
            return False
        with self.db.connect() as conn:
            warehouse = conn.execute(
                "SELECT id FROM employees WHERE player_id=? AND role='warehouse' AND active=1 LIMIT 1",
                (player_id,),
            ).fetchone()
            if warehouse:
                warehouse_id = int(warehouse["id"])
            else:
                deposit = 700_000
                cur = conn.execute(
                    """INSERT INTO employees(
                           player_id, alias, role, deposit, has_car,
                           reliability, attention, honesty, loyalty, stress
                       ) VALUES (?, 'Маяк', 'warehouse', ?, 1, 0.91, 0.88, 0.93, 0.78, 10)""",
                    (player_id, deposit),
                )
                warehouse_id = int(cur.lastrowid)
            deposits = int(conn.execute(
                "SELECT COALESCE(SUM(deposit),0) FROM employees WHERE player_id=? AND active=1",
                (player_id,),
            ).fetchone()[0])
            conn.execute("UPDATE shops SET balance=balance+? WHERE player_id=?", (deposits, player_id))
            conn.execute(
                "INSERT INTO ledger(player_id, amount, kind, note) VALUES (?, ?, 'deposit_in', 'Стартовые депозиты команды')",
                (player_id, deposits),
            )
            conn.execute(
                "UPDATE batches SET responsible_employee_id=? WHERE player_id=? AND responsible_employee_id IS NULL",
                (warehouse_id, player_id),
            )
        return True''',
    )
    for name in ("warehouse_staff_for_offer", "buy_offer_for_employee", "employee_details"):
        remove_method(path, "OperationsGameService", name)


def merge_workflow_final() -> None:
    path = APP / "workflow.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace("from .runtime import ROLE_MARKET_PAY\n", "")
    write(path, text)

    replace_method(
        path,
        "WorkflowSimulationEngine",
        "_simulate_management_events",
        r'''    def _simulate_management_events(self, conn, player_id: int, sim_hours: float, now) -> int:
        created = 0
        hours = min(max(0.0, sim_hours), 12.0)
        if self.rng.random() < 1 - math.exp(-0.035 * hours):
            client = conn.execute(
                "SELECT * FROM clients WHERE player_id=? AND shop_orders>0 ORDER BY RANDOM() LIMIT 1",
                (player_id,),
            ).fetchone()
            if client:
                percent = self.rng.choice([2, 3, 4, 5])
                conn.execute(
                    """INSERT INTO inbox(player_id, kind, priority, title, body, payload_json, expires_at)
                       VALUES (?, 'discount_request', 'important', 'Просьба постоянного клиента', ?, ?, ?)""",
                    (
                        player_id,
                        f"{client['alias']} просит небольшую скидку.\n\nРазмер: <b>{percent}%</b>\nПричина: не хватает суммы после изменения курса.",
                        json.dumps({"client_id": client["id"], "percent": percent}, ensure_ascii=False),
                        iso(now + self._game_hours_to_real(player_id, 0.75)),
                    ),
                )
                created += 1

        created += self._check_overexposure_risk(conn, player_id, sim_hours, now)
        employees = conn.execute(
            "SELECT * FROM employees WHERE player_id=? AND active=1 AND available=1 ORDER BY id",
            (player_id,),
        ).fetchall()
        for employee in employees:
            if self.employee_exposure(conn, player_id, int(employee["id"])) > 0:
                continue
            if conn.execute(
                "SELECT 1 FROM employee_tasks WHERE player_id=? AND employee_id=? AND status='active' LIMIT 1",
                (player_id, employee["id"]),
            ).fetchone():
                continue
            if conn.execute(
                """SELECT 1 FROM inbox WHERE player_id=? AND status='open' AND kind='resignation_notice'
                   AND json_extract(payload_json, '$.employee_id')=? LIMIT 1""",
                (player_id, employee["id"]),
            ).fetchone():
                continue
            loyalty_pressure = max(0.0, 0.58 - float(employee["loyalty"]))
            stress_pressure = max(0.0, float(employee["stress"]) - 72.0) / 100.0
            probability = 1.0 - math.exp(-(loyalty_pressure * 0.020 + stress_pressure * 0.012) * hours)
            if probability <= 0 or self.rng.random() >= probability:
                continue
            payout = int(employee["deposit"]) + int(employee["wages_accrued"])
            role = "оптовый" if employee["role"] == "warehouse" else "розничный"
            conn.execute("UPDATE employees SET available=0, unavailable_until=NULL WHERE id=?", (employee["id"],))
            body = (
                f"{employee['alias']} сообщил, что хочет закончить работу.\n\n"
                f"Роль: {role}\nТовар на ответственности: 0 ₽\n"
                f"Депозит к возврату: {employee['deposit']:,} ₽\n"
                f"Начисленная зарплата: {employee['wages_accrued']:,} ₽\n"
                f"Полный расчёт: <b>{payout:,} ₽</b>\n\n"
                "Сотрудник больше не берёт новые задачи. Проведи увольнение и расчёт из его профиля."
            )
            conn.execute(
                """INSERT INTO inbox(player_id, kind, priority, title, body, payload_json)
                   VALUES (?, 'resignation_notice', 'important', 'Сотрудник хочет уйти', ?, ?)""",
                (player_id, body, json.dumps({"employee_id": int(employee["id"])}, ensure_ascii=False)),
            )
            created += 1
            break
        return created''',
    )

    replace_method(
        path,
        "WorkflowGameService",
        "change_employee_role",
        r'''    def change_employee_role(self, player_id: int, employee_id: int) -> str:
        with self.db.connect() as conn:
            employee = conn.execute(
                "SELECT * FROM employees WHERE id=? AND player_id=? AND active=1",
                (employee_id, player_id),
            ).fetchone()
            if not employee:
                return "Сотрудник недоступен."
            exposure = self.simulation.employee_exposure(conn, player_id, employee_id)
            active_task = conn.execute(
                "SELECT 1 FROM employee_tasks WHERE employee_id=? AND status='active' LIMIT 1",
                (employee_id,),
            ).fetchone()
            pending = conn.execute(
                """SELECT 1 FROM retail_allocations
                   WHERE player_id=? AND status IN ('waiting','preparing')
                     AND (retail_employee_id=? OR wholesale_employee_id=?) LIMIT 1""",
                (player_id, employee_id, employee_id),
            ).fetchone()
            if exposure > 0 or active_task or pending:
                return "Сначала сотрудник должен завершить текущие задачи и не иметь назначенного товара."
            new_role = "warehouse" if employee["role"] == "courier" else "courier"
            conn.execute("UPDATE employees SET role=? WHERE id=?", (new_role, employee_id))
        role_title = "оптовый" if new_role == "warehouse" else "розничный"
        return f"{employee['alias']} переведён в роль «{role_title}»."''',
    )
    replace_method(
        path,
        "WorkflowGameService",
        "fire_employee",
        r'''    def fire_employee(self, player_id: int, employee_id: int) -> dict:
        with self.db.connect() as conn:
            pending = conn.execute(
                """SELECT 1 FROM retail_allocations
                   WHERE player_id=? AND status IN ('waiting','preparing')
                     AND (retail_employee_id=? OR wholesale_employee_id=?) LIMIT 1""",
                (player_id, employee_id, employee_id),
            ).fetchone()
            task = conn.execute(
                "SELECT 1 FROM employee_tasks WHERE employee_id=? AND status='active' LIMIT 1",
                (employee_id,),
            ).fetchone()
        if pending or task or self._employee_exposure(player_id, employee_id) > 0:
            return {
                "status": "inventory",
                "message": "Нельзя уволить сотрудника: у него есть товар, назначенная передача или незавершённая задача.",
            }
        return super().fire_employee(player_id, employee_id)''',
    )
    try:
        remove_method(path, "WorkflowGameService", "employee_details")
    except RuntimeError:
        pass

    final_path = APP / "workflow_final.py"
    if final_path.exists():
        final_path.unlink()
    staff = APP / "staff_insights.py"
    text = staff.read_text(encoding="utf-8")
    text = text.replace(
        "from .workflow_final import FinalWorkflowGameService, FinalWorkflowSimulationEngine",
        "from .workflow import WorkflowGameService, WorkflowSimulationEngine",
    )
    text = text.replace("class StaffInsightSimulationEngine(FinalWorkflowSimulationEngine):", "class StaffInsightSimulationEngine(WorkflowSimulationEngine):")
    text = text.replace("class StaffInsightGameService(FinalWorkflowGameService):", "class StaffInsightGameService(WorkflowGameService):")
    write(staff, text)
    try:
        remove_method(staff, "StaffInsightGameService", "employee_details")
    except RuntimeError:
        pass


def clean_courier_profiles_and_hiring() -> None:
    path = APP / "courier_core.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace("            self._sync_legacy_mirrors_conn(conn, int(row[\"id\"]))\n", "")
    write(path, text)
    remove_method(path, "CourierCoreSimulationEngine", "_sync_legacy_mirrors_conn")
    replace_method(
        path,
        "CourierCoreGameService",
        "hire_candidate",
        r'''    def hire_candidate(self, player_id: int, candidate_id: int) -> str:
        with self.db.connect() as conn:
            candidate = conn.execute(
                "SELECT * FROM candidates WHERE id=? AND player_id=? AND status='open'",
                (candidate_id, player_id),
            ).fetchone()
            if not candidate:
                return "Кандидат уже недоступен."
            profile = conn.execute(
                "SELECT * FROM courier_candidate_profiles WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
            deposit = int(candidate["deposit"])
            cur = conn.execute(
                """INSERT INTO employees(
                       player_id, alias, role, deposit, has_car,
                       reliability, attention, honesty, loyalty
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    player_id, candidate["alias"], candidate["role"], deposit,
                    candidate["has_car"], candidate["reliability"], candidate["attention"],
                    candidate["honesty"], candidate["loyalty"],
                ),
            )
            employee_id = int(cur.lastrowid)
            conn.execute("UPDATE shops SET balance=balance+? WHERE player_id=?", (deposit, player_id))
            conn.execute(
                """INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note)
                   VALUES (?, ?, 'deposit_in', 'employee', ?, ?)""",
                (player_id, deposit, employee_id, f"Стартовый депозит сотрудника {candidate['alias']}"),
            )
            conn.execute("UPDATE candidates SET status='hired' WHERE id=?", (candidate_id,))
            if candidate["role"] == "courier" and profile:
                conn.execute(
                    """INSERT INTO courier_profiles(
                           employee_id, player_id, pace, precision, resilience, integrity, trait
                       ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        employee_id, player_id, profile["pace"], profile["precision"],
                        profile["resilience"], profile["integrity"], profile["trait"],
                    ),
                )
        role = "Розничный сотрудник" if candidate["role"] == "courier" else "Оптовый сотрудник"
        return f"<b>{candidate['alias']} принят.</b>\n\nРоль: {role}\nСтартовый депозит: {deposit:,} ₽\nУсловия оплаты: общие для роли."''',
    )


def clean_customer_trust() -> None:
    path = APP / "customer_trust.py"
    text = path.read_text(encoding="utf-8")
    text = re.sub(
        r'\n        # Keep the old technical field coherent.*?\n        conn\.execute\(\n            "UPDATE shops SET rating=\? WHERE player_id=\?",\n            \(clamp\(trust / 20\.0, 1\.0, 5\.0\), player_id\),\n        \)',
        '',
        text,
        count=1,
        flags=re.S,
    )
    write(path, text)


def clean_navigation() -> None:
    path = APP / "ui_navigation.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        '''    elif kind == "raise_request":\n        rows.append([\n            InlineKeyboardButton(text="Согласиться", callback_data=f"staff:raiseaccept:{item_id}:{page}"),\n            InlineKeyboardButton(text="Торговаться", callback_data=f"staff:raise:{item_id}:{page}"),\n        ])\n        rows.append([InlineKeyboardButton(text="Отказать", callback_data=f"staff:deny:{item_id}:{page}")])\n    elif kind in {"leave_request", "advance_request", "discount_request"}:''',
        '''    elif kind == "discount_request":''',
    )
    write(path, text)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # Remove the top-level negotiation keyboard.
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "negotiation_keyboard":
                lines = path.read_text(encoding="utf-8").splitlines()
                lines[node.lineno - 1:node.end_lineno] = []
                write(path, "\n".join(lines))
                break
    except Exception:
        raise
    # Nested handlers are easiest to delete by their callback block, from helper to router return.
    text = path.read_text(encoding="utf-8")
    start = text.find("    async def show_negotiation(")
    if start != -1:
        end = text.find("\n    return router", start)
        if end == -1:
            raise RuntimeError("navigation return router not found")
        text = text[:start] + text[end:]
    write(path, text)


def clean_schema() -> None:
    path = APP / "schema.sql"
    text = path.read_text(encoding="utf-8")
    for pattern in (
        r"^    rating REAL NOT NULL DEFAULT 4\.0,\n",
        r"^    pay_per_job INTEGER NOT NULL DEFAULT 0,\n",
        r"^    deposit_contribution_pct INTEGER NOT NULL DEFAULT 0,\n",
        r"^    loyalty REAL NOT NULL,\n",
    ):
        text, count = re.subn(pattern, "", text, count=1, flags=re.M)
        if count != 1:
            raise RuntimeError(f"schema pattern not found: {pattern}")
    write(path, text)


def update_tests() -> None:
    path = TESTS / "test_procurement_market.py"
    text = path.read_text(encoding="utf-8").replace("assert len(products) == 3", "assert len(products) == 6")
    write(path, text)

    path = TESTS / "test_global_packaging.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        '''INSERT INTO employees(\n                   player_id, alias, role, pay_per_job, deposit,\n                   deposit_contribution_pct, has_car,\n                   reliability, attention, honesty, loyalty, stress\n               ) VALUES (1001, 'Новый', 'courier', 1500, 50000, 20, 0, 0.8, 0.8, 0.8, 0.6, 10)''',
        '''INSERT INTO employees(\n                   player_id, alias, role, deposit, has_car,\n                   reliability, attention, honesty, loyalty, stress\n               ) VALUES (1001, 'Новый', 'courier', 50000, 0, 0.8, 0.8, 0.8, 0.6, 10)''',
    )
    write(path, text)

    path = TESTS / "test_workflow_pipeline.py"
    text = path.read_text(encoding="utf-8")
    old = '''    with db.connect() as conn:\n        retail = conn.execute(\n            "SELECT id FROM employees WHERE player_id=1001 AND role='courier' LIMIT 1"\n        ).fetchone()\n    game.adjust_global_packaging_rule(1001, 5, 10)\n    rule = next(row for row in game.packaging_rules(1001, int(retail["id"])) if row["product_id"] == 1)\n    assert int(rule["pct_1"]) + int(rule["pct_2"]) + int(rule["pct_5"]) == 100\n    assert int(rule["pct_5"]) == 20'''
    new = '''    game.adjust_global_packaging_rule(1001, 5, 10)\n    rule = game.global_packaging_rule(1001)\n    assert rule["pct_1"] + rule["pct_2"] + rule["pct_5"] == 100\n    assert rule["pct_5"] == 20'''
    if old not in text:
        raise RuntimeError("workflow packaging test block not found")
    write(path, text.replace(old, new, 1))


def assert_removed_references() -> None:
    forbidden = {
        "pay_per_job": [],
        "desired_pay": [],
        "offered_pay": [],
        "raise_request": [],
        "leave_request": [],
        "advance_request": [],
        "workflow_final": [],
        "services import FinalGameService": [],
        "_sync_legacy_mirrors_conn": [],
        "shops SET rating": [],
        "clients SET loyalty": [],
    }
    for path in APP.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token, hits in forbidden.items():
            if token.lower() in text.lower():
                hits.append(path.name)
    bad = {token: hits for token, hits in forbidden.items() if hits}
    if bad:
        raise RuntimeError(f"legacy references remain: {bad}")


def main() -> None:
    clean_simulation()
    clean_runtime()
    clean_nightshift()
    clean_game_service()
    write_dispute_payments()
    clean_operations()
    merge_workflow_final()
    clean_courier_profiles_and_hiring()
    clean_customer_trust()
    clean_navigation()
    clean_schema()
    update_tests()
    assert_removed_references()


if __name__ == "__main__":
    main()
