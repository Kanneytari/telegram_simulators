from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "shadow_market_simulator" / "app"
TESTS = ROOT / "shadow_market_simulator" / "tests"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def replace_required(path: Path, old: str, new: str, minimum: int = 1) -> None:
    text = read(path)
    count = text.count(old)
    if count < minimum:
        raise RuntimeError(f"{path}: expected >= {minimum} occurrences of {old!r}, found {count}")
    write(path, text.replace(old, new))


# Current menu contract: internal menu names should match visible screen names.
for folder in (APP, TESTS):
    for path in folder.glob("*.py"):
        text = read(path)
        text = text.replace("menu:procurement", "menu:product")
        text = text.replace("menu:sales", "menu:storefront")
        text = text.replace("render_procurement_root", "render_product_root")
        text = text.replace("render_sales_root", "render_storefront_root")
        # The old task name leaked the obsolete 'positions' vocabulary.
        text = text.replace("prepare_positions", "place_stashes")
        write(path, text)

# Remove the obsolete no-op 'delayed disputes' inheritance layer.
compensation = APP / "compensation.py"
text = read(compensation)
text = text.replace(
    "from .delayed_disputes import DelayedDisputeGameService, DelayedDisputeSimulationEngine",
    "from .procurement_market import ProcurementMarketGameService, ProcurementMarketSimulationEngine",
)
text = text.replace("class CompensationSimulationEngine(DelayedDisputeSimulationEngine):", "class CompensationSimulationEngine(ProcurementMarketSimulationEngine):")
text = text.replace("class CompensationGameService(DelayedDisputeGameService):", "class CompensationGameService(ProcurementMarketGameService):")
write(compensation, text)

old_disputes = APP / "delayed_disputes.py"
if old_disputes.exists():
    old_disputes.unlink()

old_test = TESTS / "test_delayed_disputes.py"
if old_test.exists():
    text = read(old_test)
    text = text.replace(
        "from app.delayed_disputes import DelayedDisputeGameService, DelayedDisputeSimulationEngine",
        "from app.procurement_market import ProcurementMarketGameService, ProcurementMarketSimulationEngine",
    )
    text = text.replace("DelayedDisputeSimulationEngine", "ProcurementMarketSimulationEngine")
    text = text.replace("DelayedDisputeGameService", "ProcurementMarketGameService")
    write(TESTS / "test_dispute_explanations.py", text)
    old_test.unlink()

# Employee active-task vocabulary shown in team buttons.
workflow = APP / "workflow.py"
replace_required(workflow, '"place_stashes": "готовит товар"', '"place_stashes": "раскидывает клады"')
staff_insights = APP / "staff_insights.py"
replace_required(staff_insights, '"place_stashes": "готовит товар"', '"place_stashes": "раскидывает клады"')

# Compute the default handoff amount in the game service, not in Telegram UI.
text = read(workflow)
old = '''        result = []
        for employee in staff:
            exposure = self._employee_exposure(player_id, int(employee["id"]))
            result.append({
                "id": int(employee["id"]),
                "alias": employee["alias"],
                "deposit": int(employee["deposit"]),
                "exposure": exposure,
                "free": max(0, int(employee["deposit"]) - exposure),
            })
        return batch, result
'''
new = '''        result = []
        remaining = max(0, int(batch["remaining"]))
        unit_cost = max(1, int(batch["unit_cost"]))
        for employee in staff:
            exposure = self._employee_exposure(player_id, int(employee["id"]))
            free = max(0, int(employee["deposit"]) - exposure)
            covered_units = free // unit_cost
            recommended_quantity = min(remaining, covered_units)
            recommended_quantity -= recommended_quantity % 5
            result.append({
                "id": int(employee["id"]),
                "alias": employee["alias"],
                "deposit": int(employee["deposit"]),
                "exposure": exposure,
                "free": free,
                "recommended_quantity": recommended_quantity,
            })
        return batch, result
'''
if old not in text:
    raise RuntimeError("workflow.py: retail_staff_for_batch block not found")
text = text.replace(old, new)
text = text.replace('f"Ответственный: <b>{employee[\'alias\']}</b>\\n"', 'f"Складмен: <b>{employee[\'alias\']}</b>\\n"')
write(workflow, text)

# Canonical batch screen uses the service recommendation immediately when a recipient is selected.
handlers = APP / "ui_staff_handlers.py"
text = read(handlers)
old_callback = 'callback_data=f"team:alloc:{batch_id}:{employee[\'id\']}:{min(10, int(batch[\'remaining\']))}"'
new_callback = 'callback_data=f"team:alloc:{batch_id}:{employee[\'id\']}:{int(employee.get(\'recommended_quantity\', 0))}"'
if old_callback not in text:
    raise RuntimeError("ui_staff_handlers.py: default allocation callback not found")
text = text.replace(old_callback, new_callback)
text = text.replace('result = f"Ответственный: {employee[\'alias\']}."', 'result = f"Складмен: {employee[\'alias\']}."')
write(handlers, text)

# ui_staff contained an older duplicate batch screen. Keep one source of truth only.
ui_staff = APP / "ui_staff.py"
text = read(ui_staff)
start = text.find("def _recipient_label(employee: dict) -> str:")
end = text.find("async def render_allocation", start)
if start == -1 or end == -1:
    raise RuntimeError("ui_staff.py: duplicate batch renderer block not found")
text = text[:start] + text[end:]
text = text.replace(
    '    quantity = max(1, min(int(quantity), int(batch["remaining"])))',
    '    quantity = max(0, min(int(quantity), int(batch["remaining"])))',
)
text = text.replace(
    'InlineKeyboardButton(text="−5", callback_data=f"team:alloc:{batch_id}:{employee_id}:{max(1, quantity-5)}")',
    'InlineKeyboardButton(text="−5", callback_data=f"team:alloc:{batch_id}:{employee_id}:{max(0, quantity-5)}")',
)
old_transfer = '    rows.append([InlineKeyboardButton(text=f"Передать {quantity} ед.", callback_data=f"team:allocdo:{batch_id}:{employee_id}:{quantity}")])\n'
new_transfer = '    if quantity > 0:\n        rows.append([InlineKeyboardButton(text=f"Передать {quantity} ед.", callback_data=f"team:allocdo:{batch_id}:{employee_id}:{quantity}")])\n'
if old_transfer not in text:
    raise RuntimeError("ui_staff.py: transfer button line not found")
text = text.replace(old_transfer, new_transfer)
old_risk = '    text += f"\\n🔴 Не покрыто депозитом: {money(unsecured)}" if unsecured else "\\n🟢 Полностью покрыто депозитом."\n'
new_risk = '''    if quantity <= 0:
        text += "\\n\\nСвободного залога недостаточно даже для 5 ед. Можно выбрать количество вручную, если готов оставить часть товара непокрытой."
    else:
        text += f"\\n🔴 Не покрыто депозитом: {money(unsecured)}" if unsecured else "\\n🟢 Полностью покрыто депозитом."
'''
if old_risk not in text:
    raise RuntimeError("ui_staff.py: allocation risk line not found")
text = text.replace(old_risk, new_risk)
write(ui_staff, text)

# Tests for the exact new default and the player-facing activity status.
ux_test = TESTS / "test_ux_clarity.py"
text = read(ux_test)
if "test_recommended_handoff_uses_free_deposit" not in text:
    text += r'''


def test_recommended_handoff_uses_free_deposit_and_rounds_to_five(tmp_path):
    db, _, game, _ = make_system(tmp_path)
    with db.connect() as conn:
        courier = conn.execute(
            "SELECT id FROM employees WHERE player_id=? AND role='courier' ORDER BY id LIMIT 1",
            (PLAYER_ID,),
        ).fetchone()
        batch = conn.execute(
            "SELECT id, unit_cost FROM batches WHERE player_id=? AND status='warehouse' ORDER BY id LIMIT 1",
            (PLAYER_ID,),
        ).fetchone()
        assert courier and batch
        employee_id = int(courier["id"])
        batch_id = int(batch["id"])
        unit_cost = int(batch["unit_cost"])
        exposure = game._employee_exposure(PLAYER_ID, employee_id)
        conn.execute("UPDATE employees SET deposit=? WHERE id=?", (exposure + unit_cost * 27, employee_id))
        conn.execute("UPDATE batches SET remaining=18 WHERE id=?", (batch_id,))

    current_batch, staff = game.retail_staff_for_batch(PLAYER_ID, batch_id)
    employee = next(row for row in staff if int(row["id"]) == employee_id)
    assert int(current_batch["remaining"]) == 18
    assert int(employee["recommended_quantity"]) == 15


def test_recommended_handoff_is_zero_when_deposit_covers_less_than_five(tmp_path):
    db, _, game, _ = make_system(tmp_path)
    with db.connect() as conn:
        courier = conn.execute(
            "SELECT id FROM employees WHERE player_id=? AND role='courier' ORDER BY id LIMIT 1",
            (PLAYER_ID,),
        ).fetchone()
        batch = conn.execute(
            "SELECT id, unit_cost FROM batches WHERE player_id=? AND status='warehouse' ORDER BY id LIMIT 1",
            (PLAYER_ID,),
        ).fetchone()
        assert courier and batch
        employee_id = int(courier["id"])
        unit_cost = int(batch["unit_cost"])
        exposure = game._employee_exposure(PLAYER_ID, employee_id)
        conn.execute("UPDATE employees SET deposit=? WHERE id=?", (exposure + unit_cost * 4, employee_id))

    _, staff = game.retail_staff_for_batch(PLAYER_ID, int(batch["id"]))
    employee = next(row for row in staff if int(row["id"]) == employee_id)
    assert int(employee["recommended_quantity"]) == 0
'''
write(ux_test, text)

# Update assertions whose visible status intentionally changed.
for path in TESTS.glob("*.py"):
    text = read(path)
    text = text.replace("готовит товар", "раскидывает клады")
    write(path, text)

print("current NIGHTSHIFT cleanup applied")
