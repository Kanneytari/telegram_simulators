from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "shadow_market_simulator" / "app"

def read(path): return Path(path).read_text(encoding="utf-8")
def write(path, text): Path(path).write_text(text, encoding="utf-8")
def once(path, old, new):
    text = read(path); count = text.count(old)
    if count != 1: raise RuntimeError(f"{path}: expected one match, got {count}: {old[:80]!r}")
    write(path, text.replace(old, new, 1))
def section(path, start, end, new):
    text = read(path); i = text.find(start); j = text.find(end, i + len(start))
    if i < 0 or j < 0: raise RuntimeError(f"{path}: section missing {start!r} -> {end!r}")
    write(path, text[:i] + new.rstrip() + "\n\n" + text[j:])

# One-time tips.
common = APP / "ui_common.py"
once(common,
     'def normalize_text(text: str) -> str:\n    return _THOUSANDS_COMMA.sub(" ", text)\n',
     'def normalize_text(text: str) -> str:\n    return _THOUSANDS_COMMA.sub(" ", text)\n\n\ndef claim_tip(db, player_id: int, code: str) -> bool:\n    with db.connect() as conn:\n        cur = conn.execute(\n            "INSERT OR IGNORE INTO player_tips(player_id, code) VALUES (?, ?)",\n            (player_id, code),\n        )\n    return cur.rowcount > 0\n')

# Main navigation.
nav = APP / "ui_navigation.py"
section(nav, "def home_keyboard(", "def _home_snapshot(", r'''def home_keyboard(opened: int, urgent: int, *, is_admin: bool = False) -> InlineKeyboardMarkup:
    inbox = f"📨 Входящие · {opened}"
    if urgent:
        inbox += f" · 🔴 {urgent}"
    rows = [
        [InlineKeyboardButton(text=inbox, callback_data="menu:inbox")],
        [
            InlineKeyboardButton(text="📦 Товар", callback_data="menu:procurement"),
            InlineKeyboardButton(text="🏷 Витрина", callback_data="menu:sales"),
        ],
        [
            InlineKeyboardButton(text="👥 Команда", callback_data="menu:team"),
            InlineKeyboardButton(text="📊 Аналитика", callback_data="menu:analytics"),
        ],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="🛠 Админ", callback_data="admin:panel")])
    rows.append([InlineKeyboardButton(text="Обновить", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)''')
section(nav, "def _home_snapshot(", "async def render_home(", r'''def _home_snapshot(db, game, simulation, player_id: int) -> tuple[str, int, int]:
    simulation.advance(player_id)
    game.process_payroll(player_id)
    window = _window("7")
    with db.connect() as conn:
        shop = conn.execute("SELECT * FROM shops WHERE player_id=?", (player_id,)).fetchone()
        deposits = int(conn.execute(
            "SELECT COALESCE(SUM(deposit),0) FROM employees WHERE player_id=? AND active=1",
            (player_id,),
        ).fetchone()[0])
        wages = int(conn.execute(
            "SELECT COALESCE(SUM(wages_accrued),0) FROM employees WHERE player_id=? AND active=1",
            (player_id,),
        ).fetchone()[0])
        inbox = conn.execute(
            """SELECT COUNT(*) opened,
                      SUM(CASE WHEN priority='urgent' THEN 1 ELSE 0 END) urgent,
                      SUM(CASE WHEN priority='important' THEN 1 ELSE 0 END) important
               FROM inbox WHERE player_id=? AND status='open'""",
            (player_id,),
        ).fetchone()
        current = _order_metrics(conn, player_id, window["current_start"], window["current_end"])
        previous = _order_metrics(conn, player_id, window["previous_start"], window["previous_end"])
        products = _product_metrics(conn, player_id, window["current_start"], window["current_end"], 7)
        stressed = conn.execute(
            """SELECT alias, stress FROM employees
               WHERE player_id=? AND active=1 AND role='courier' AND stress>=62
               ORDER BY stress DESC LIMIT 1""",
            (player_id,),
        ).fetchone()
        ready_batch = conn.execute(
            """SELECT id FROM batches
               WHERE player_id=? AND status='warehouse' AND remaining>0
               ORDER BY id LIMIT 1""",
            (player_id,),
        ).fetchone()

    opened = int(inbox["opened"] or 0)
    urgent = int(inbox["urgent"] or 0)
    important = int(inbox["important"] or 0)
    free_cash = int(shop["balance"]) - int(shop["reserve_target"]) - deposits - wages
    compare_ready = _comparison_ready(shop, window)
    earned_trend = signed_pct_change(current["earned"], previous["earned"]) if compare_ready else ""
    orders_trend = signed_pct_change(current["orders"], previous["orders"]) if compare_ready else ""

    alerts: list[str] = []
    if urgent:
        alerts.append(f"🔴 {urgent} событий требуют решения")
    elif important:
        alerts.append(f"🟡 {important} событий требуют внимания")
    if stressed:
        alerts.append(f"🟡 {clean(stressed['alias'])} перегружен")
    low_stock = [p for p in products if p.get("stock_days") is not None and float(p["stock_days"]) < 3.0]
    if low_stock:
        item = min(low_stock, key=lambda row: float(row["stock_days"]))
        alerts.append(f"🟡 {clean(item['title'])}: запаса примерно на {max(1, round(float(item['stock_days'])))} дн.")
    if not alerts:
        alerts.append("Срочных проблем нет.")

    next_step = ""
    if urgent:
        next_step = "→ 🔴 Разбери срочное сообщение во Входящих."
    elif ready_batch:
        next_step = "→ Партия получена. Передай товар закладчику."

    text = (
        f"<b>🌒 {clean(shop['name'])}</b>\n\n"
        f"Баланс: <b>{money(shop['balance'])}</b>\n"
        f"Свободно: <b>{money(free_cash)}</b>\n"
        f"За 7 дней: <b>{money(current['earned'])}</b>{earned_trend} · "
        f"{current['orders']} заказов{orders_trend}\n\n"
        + "\n".join(alerts[:2])
    )
    if next_step:
        text += f"\n\n{next_step}"
    return text, opened, urgent''')
once(nav,
     '                "<b>🌒 NIGHTSHIFT</b>\\n\\n"\n                "Магазин работает, даже когда ты офлайн. Следи за входящими, товаром и командой.",',
     '                "<b>🌒 NIGHTSHIFT</b>\\n\\n"\n                "Ты управляешь магазином, который работает даже когда ты офлайн.\\n\\n"\n                "Закупай товар, распределяй его между сотрудниками, управляй витриной и разбирай проблемы.\\n\\n"\n                "<b>Товар → Склад → Закладчики → Витрина → Продажи</b>",')

# Commerce/product/storefront.
commerce = APP / "ui_commerce.py"
once(commerce, "from .ui_common import clean, money, nav_row, notice, present, rating", "from .ui_common import claim_tip, clean, money, nav_row, notice, present, rating")
section(commerce, "def _procurement_products_keyboard(", "async def render_procurement_root(", r'''def _procurement_products_keyboard(db, player_id: int, products) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        text=f"{product['title']} · {_stock_status(db, player_id, int(product['id']))} · {product['total']} предложений",
        callback_data=f"proc:product:{product['id']}",
    )] for product in products]
    with db.connect() as conn:
        batch_count = int(conn.execute(
            """SELECT COUNT(*) FROM batches
               WHERE player_id=? AND status IN ('receiving','warehouse') AND remaining>0""",
            (player_id,),
        ).fetchone()[0])
    rows.append([InlineKeyboardButton(text=f"Склад · {batch_count} партий", callback_data="team:batches")])
    rows.append([
        InlineKeyboardButton(text="Обновить", callback_data="menu:procurement"),
        InlineKeyboardButton(text="Меню", callback_data="menu:home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)''')
once(commerce, '    body = f"<b>📦 Закупки</b>\\n\\nМожно потратить: <b>{money(free_cash)}</b>"', '    body = f"<b>📦 Товар</b>\\n\\nСвободно: <b>{money(free_cash)}</b>"')
section(commerce, "async def render_offer(", "async def render_offer_staff(", r'''async def render_offer(target: Message, game, player_id: int, offer_id: int, employee_id: int | None = None) -> None:
    offer = game.procurement_offer(player_id, offer_id)
    if not offer:
        await render_procurement_root(target, game.db, game, player_id, flash="Предложение уже исчезло с рынка.")
        return
    typical = game.offer_typical_unit_cost(offer)
    delta = (float(offer["unit_cost"]) / typical - 1.0) * 100.0 if typical else 0.0
    quality = float(offer["resolved_quality_mean"])
    reliability = float(offer["resolved_reliability"]) * 100.0
    total = int(offer["quantity"] * offer["unit_cost"])
    staff = game.warehouse_staff_for_offer(player_id, offer_id)
    selected = next((row for row in staff if int(row["id"]) == int(employee_id or -1)), None) or _best_warehouse(staff)

    if delta < -0.5:
        price_relation = f"на {abs(delta):.0f}% дешевле обычного"
    elif delta > 0.5:
        price_relation = f"на {delta:.0f}% дороже обычного"
    else:
        price_relation = "около обычной цены"
    text = (
        f"<b>{clean(offer['product_title'])} · {offer['quantity']} ед.</b>\n\n"
        f"{money(total)} · {price_relation}\n"
        f"Качество: <b>{_quality_label(quality)}</b> · {quality:.0f}/100\n"
        f"Надёжность поставки: {reliability:.0f}%"
    )
    if selected:
        unsecured = int(selected.get("unsecured_after", 0))
        text += f"\n\nСкладмен: <b>{clean(selected['alias'])}</b>"
        if unsecured:
            text += f"\n🔴 Не покрыто депозитом: {money(unsecured)}"
            if claim_tip(game.db, player_id, "uncovered_stock"):
                text += "\n\n💡 Депозит сотрудника покрывает возможную потерю товара. Всё сверх депозита - риск магазина."
        else:
            text += "\n🟢 Товар полностью покрыт его депозитом."
    else:
        text += "\n\n🔴 Нет активного складмена."
    await present(target, text, _offer_keyboard(offer_id, int(offer["product_id"]), selected, staff))''')
text = read(commerce)
text = text.replace('text="Сменить ответственного"', 'text="Сменить складмена"')
text = text.replace('"<b>Ответственный</b>\\n\\n', '"<b>Складмен для закупки</b>\\n\\n')
text = text.replace('rows.append(nav_row("menu:procurement", "← Закупки"))', 'rows.append(nav_row("menu:procurement", "← Товар"))')
text = text.replace('rows.append(nav_row("menu:sales", "← Продажа"))', 'rows.append(nav_row("menu:sales", "← Витрина"))')
text = text.replace('nav_row("menu:sales", "← Продажа")', 'nav_row("menu:sales", "← Витрина")')
text = text.replace('flash = result.split("\\n\\n", 1)[0]', 'flash = result')
write(commerce, text)
once(commerce,
     '        "<b>🏷 Продажа</b>\\n\\n"\n        f"Доверие {trust[\'trust_score\']:.0f}/100 · до ~+{trust[\'premium_allowance\'] * 100:.0f}% к рынку переносится нормально."',
     '        "<b>🏷 Витрина</b>\\n\\n"\n        f"Доверие: {trust[\'trust_score\']:.0f}/100\\n"\n        f"Наценка до ~+{trust[\'premium_allowance\'] * 100:.0f}% обычно не снижает спрос."')
once(commerce,
     '        text=f"×{listing[\'pack_size\']} · {money(listing[\'price\'])} · {int(listing[\'positions\'])} поз.",',
     '        text=f"×{listing[\'pack_size\']} · {money(listing[\'price\'])} · доступно {int(listing[\'positions\'])}",')
once(commerce, 'f"Готово к продаже: {int(row[\'positions\'])} поз."', 'f"Доступно: {int(row[\'positions\'])}"')
section(commerce, "async def render_packaging(", "def build_commerce_router(", r'''async def render_packaging(target: Message, game, player_id: int) -> None:
    rule = game.global_packaging_rule(player_id)
    text = (
        "<b>Фасовки</b>\n\n"
        "Новые партии распределяются так:\n\n"
        f"×1 · <b>{rule['pct_1']}%</b>\n"
        f"×2 · <b>{rule['pct_2']}%</b>\n"
        f"×5 · <b>{rule['pct_5']}%</b>"
    )
    if claim_tip(game.db, player_id, "packaging"):
        text += "\n\n💡 Эти доли применяются к товару, который закладчики будут готовить к витрине после следующих передач."
    await present(target, text, packaging_keyboard(rule))''')

print("navigation/commerce UX transform ok")
