from pathlib import Path
import re

ROOT = Path('shadow_market_simulator')


def replace_top_level_function(text: str, name: str, replacement: str) -> str:
    start_match = re.search(rf'(?m)^(?:async def|def) {re.escape(name)}\(', text)
    if not start_match:
        raise SystemExit(f'function not found: {name}')
    start = start_match.start()
    next_match = re.search(r'(?m)^(?:@|async def|def|class) ', text[start_match.end():])
    end = start_match.end() + next_match.start() if next_match else len(text)
    return text[:start] + replacement.rstrip() + '\n\n' + text[end:]


ui_path = ROOT / 'app/ui_commerce.py'
ui = ui_path.read_text(encoding='utf-8')

ui = replace_top_level_function(
    ui,
    '_procurement_products_keyboard',
    '''def _warehouse_batch_count(db, player_id: int) -> int:
    with db.connect() as conn:
        return int(conn.execute(
            """SELECT COUNT(*) FROM batches
               WHERE player_id=? AND status IN ('receiving','warehouse') AND remaining>0""",
            (player_id,),
        ).fetchone()[0])


def _product_root_keyboard(batch_count: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤝 Поставщики", callback_data="proc:suppliers")],
        [InlineKeyboardButton(text=f"📦 Склад · {batch_count}", callback_data="team:batches")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="menu:home")],
    ])


def _procurement_products_keyboard(db, player_id: int, products) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for product in products:
        status = _stock_status(db, player_id, int(product["id"]))
        text = str(product["title"])
        if status != "нет запаса":
            text += f" · 🚚 {status}"
        rows.append([
            InlineKeyboardButton(
                text=text,
                callback_data=f"proc:product:{product['id']}",
            )
        ])
    rows.append(nav_row("menu:product", "← Товар"))
    return InlineKeyboardMarkup(inline_keyboard=rows)''',
)

ui = replace_top_level_function(
    ui,
    'render_product_root',
    '''async def render_product_root(target: Message, db, game, player_id: int, *, flash: str | None = None) -> None:
    with db.connect() as conn:
        free_cash = game._free_cash_conn(conn, player_id) if hasattr(game, "_free_cash_conn") else int(
            conn.execute("SELECT balance FROM shops WHERE player_id=?", (player_id,)).fetchone()[0]
        )
    body = f"<b>📦 Товар</b>\\n\\nСвободно: <b>{money(free_cash)}</b>"
    if game.needs_first_handoff_tutorial(player_id):
        body += "\\n\\n" + tutorial_hint("Нажми на кнопку 📦 Склад")
    await present(target, notice(flash, body), _product_root_keyboard(_warehouse_batch_count(db, player_id)))''',
)

supplier_renderer = '''@tutorial_hooks.handoff_suppliers_root
@tutorial_hooks.affordable_empty_suppliers_root
@tutorial_hooks.soft_suppliers_root
async def render_suppliers_root(target: Message, db, game, player_id: int, *, flash: str | None = None) -> None:
    products = game.procurement_products(player_id)
    body = "<b>🤝 Поставщики</b>\\n\\nВыберите категорию товара."
    await present(target, notice(flash, body), _procurement_products_keyboard(db, player_id, products))


'''
marker = 'def _offers_keyboard(product_id: int, offers) -> InlineKeyboardMarkup:'
if marker not in ui:
    raise SystemExit('offers keyboard marker not found')
ui = ui.replace(marker, supplier_renderer + marker, 1)

old_back = '    rows.append(nav_row("menu:product", "← Товар"))\n    return InlineKeyboardMarkup(inline_keyboard=rows)\n\n\n@tutorial_hooks.handoff_procurement_product'
new_back = '    rows.append(nav_row("proc:suppliers", "← Поставщики"))\n    return InlineKeyboardMarkup(inline_keyboard=rows)\n\n\n@tutorial_hooks.handoff_procurement_product'
if old_back not in ui:
    raise SystemExit('offers back navigation not found')
ui = ui.replace(old_back, new_back, 1)

router_marker = '    @router.callback_query(F.data.startswith("proc:product:"))\n'
supplier_handler = '''    @router.callback_query(F.data == "proc:suppliers")
    async def suppliers(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_suppliers_root(callback.message, db, game, callback.from_user.id)

'''
if router_marker not in ui:
    raise SystemExit('proc product router marker not found')
ui = ui.replace(router_marker, supplier_handler + router_marker, 1)
ui_path.write_text(ui, encoding='utf-8')


hooks_path = ROOT / 'app/tutorial/hooks.py'
hooks = hooks_path.read_text(encoding='utf-8')

hooks = replace_top_level_function(
    hooks,
    'soft_product_root',
    '''def soft_product_root(original):
    @wraps(original)
    async def render_product_root(target, db, game, player_id: int, *, flash: str | None=None) -> None:
        from .. import ui_commerce
        state = sync_tutorial_state(db, player_id)
        if not state or not state['active'] or state['stage'] != STAGE_PROCUREMENT:
            await original(target, db, game, player_id, flash=flash)
            return
        body = f'<b>📦 Товар</b>\\n\\nСвободно: <b>{money(_free_cash(game, player_id))}</b>\\n\\n' + tutorial_hint('Нажми [🤝 Поставщики]')
        if flash:
            body = f'{flash}\\n\\n{body}'
        markup = ui_commerce._product_root_keyboard(ui_commerce._warehouse_batch_count(db, player_id))
        await present(target, body, markup)
    decorated = render_product_root

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded''',
)

soft_suppliers = '''def soft_suppliers_root(original):
    @wraps(original)
    async def render_suppliers_root(target, db, game, player_id: int, *, flash: str | None=None) -> None:
        from .. import ui_commerce
        state = sync_tutorial_state(db, player_id)
        if not state or not state['active'] or state['stage'] != STAGE_PROCUREMENT:
            await original(target, db, game, player_id, flash=flash)
            return
        products = game.procurement_products(player_id)
        body = '<b>🤝 Поставщики</b>\\n\\n' + tutorial_hint('Выбери товар для первой закупки.')
        if flash:
            body = f'{flash}\\n\\n{body}'
        await present(target, body, ui_commerce._procurement_products_keyboard(db, player_id, products))
    decorated = render_suppliers_root

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


'''
marker = 'def soft_procurement_product(original):'
if marker not in hooks:
    raise SystemExit('soft procurement marker not found')
hooks = hooks.replace(marker, soft_suppliers + marker, 1)

hooks = replace_top_level_function(
    hooks,
    'affordable_empty_product_root',
    '''def affordable_empty_product_root(original):
    @wraps(original)
    async def render_product_root(target, db, game, player_id: int, *, flash: str | None=None) -> None:
        from .. import ui_commerce
        products = game.procurement_products(player_id)
        if any((int(product.get('total', 0)) > 0 for product in products)):
            await original(target, db, game, player_id, flash=flash)
            return
        with db.connect() as conn:
            free_cash = game._free_cash_conn(conn, player_id)
        body = f'<b>📦 Товар</b>\\n\\nСвободно: <b>{money(free_cash)}</b>\\n\\nДоступных предложений нет.'
        markup = ui_commerce._product_root_keyboard(ui_commerce._warehouse_batch_count(db, player_id))
        await present(target, notice(flash, body), markup)
    decorated = render_product_root

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded''',
)

affordable_suppliers = '''def affordable_empty_suppliers_root(original):
    @wraps(original)
    async def render_suppliers_root(target, db, game, player_id: int, *, flash: str | None=None) -> None:
        from .. import ui_commerce
        products = game.procurement_products(player_id)
        if any((int(product.get('total', 0)) > 0 for product in products)):
            await original(target, db, game, player_id, flash=flash)
            return
        body = '<b>🤝 Поставщики</b>\\n\\nДоступных предложений нет.'
        await present(target, notice(flash, body), ui_commerce._procurement_products_keyboard(db, player_id, products))
    decorated = render_suppliers_root

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


'''
marker = 'def affordable_empty_procurement_product(original):'
if marker not in hooks:
    raise SystemExit('affordable procurement marker not found')
hooks = hooks.replace(marker, affordable_suppliers + marker, 1)

hooks = replace_top_level_function(
    hooks,
    'handoff_product_root',
    '''def handoff_product_root(original):
    @wraps(original)
    async def render_product_root(target, db, game, player_id: int, *, flash: str | None=None) -> None:
        from .. import ui_commerce
        if not _handoff_state(db, player_id):
            await original(target, db, game, player_id, flash=flash)
            return
        free_cash = tutorial._free_cash(game, player_id)
        body = f'<b>📦 Товар</b>\\n\\nСвободно: <b>{money(free_cash)}</b>\\n\\n' + tutorial_hint('Нажми [📦 Склад]')
        markup = ui_commerce._product_root_keyboard(ui_commerce._warehouse_batch_count(db, player_id))
        await present(target, notice(flash, body), markup)
    decorated = render_product_root

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded''',
)

handoff_suppliers = '''def handoff_suppliers_root(original):
    @wraps(original)
    async def render_suppliers_root(target, db, game, player_id: int, *, flash: str | None=None) -> None:
        wrapped = _return_target(target) if _handoff_state(db, player_id) else target
        await original(wrapped, db, game, player_id, flash=flash)
    decorated = render_suppliers_root

    @wraps(original)
    def guarded(*args, **kwargs):
        db = _runtime_db(args, kwargs)
        if not runtime_enabled(db):
            return original(*args, **kwargs)
        return decorated(*args, **kwargs)

    return guarded


'''
marker = 'def handoff_procurement_product(original):'
if marker not in hooks:
    raise SystemExit('handoff procurement marker not found')
hooks = hooks.replace(marker, handoff_suppliers + marker, 1)
hooks_path.write_text(hooks, encoding='utf-8')


compact_path = ROOT / 'tests/test_compact_ui.py'
compact = compact_path.read_text(encoding='utf-8')
compact = compact.replace(
    'from app.ui_commerce import packaging_keyboard\n',
    'from app import ui_commerce\nfrom app.ui_commerce import _product_root_keyboard, packaging_keyboard\n',
    1,
)
anchor = '\ndef test_analytics_uses_same_compact_navigation_language():\n'
new_tests = '''
def test_product_root_nests_procurement_under_suppliers():
    markup = _product_root_keyboard(3)
    assert labels(markup) == [
        "🤝 Поставщики",
        "📦 Склад · 3",
        "🏠 Меню",
    ]
    assert callbacks(markup) == ["proc:suppliers", "team:batches", "menu:home"]


def test_suppliers_screen_contains_product_categories(monkeypatch):
    monkeypatch.setattr(ui_commerce, "_stock_status", lambda *_args: "нет запаса")
    markup = ui_commerce._procurement_products_keyboard(
        object(),
        1,
        [
            {"id": 1, "title": "Амфетамин"},
            {"id": 3, "title": "Кокаин"},
        ],
    )
    assert labels(markup) == ["Амфетамин", "Кокаин", "← Товар"]
    assert callbacks(markup) == ["proc:product:1", "proc:product:3", "menu:product"]

'''
if anchor not in compact:
    raise SystemExit('compact UI insertion anchor not found')
compact = compact.replace(anchor, '\n' + new_tests + 'def test_analytics_uses_same_compact_navigation_language():\n', 1)
compact_path.write_text(compact, encoding='utf-8')


guard_path = ROOT / 'tests/test_architecture_guardrails.py'
guard = guard_path.read_text(encoding='utf-8')
if 'import re\n' not in guard:
    guard = guard.replace('import ast\n', 'import ast\nimport re\n', 1)
if 'def test_tutorial_inbox_copy_has_single_owner()' not in guard:
    guard += '''\n\ndef test_tutorial_inbox_copy_has_single_owner() -> None:\n    pattern = re.compile(\n        r"UPDATE\\s+inbox\\b.{0,700}?kind\\s*=\\s*['\\\"]tutorial['\\\"]",\n        re.IGNORECASE | re.DOTALL,\n    )\n    owners = {\n        path.relative_to(APP).as_posix()\n        for path in APP.rglob("*.py")\n        if pattern.search(path.read_text(encoding="utf-8"))\n    }\n    assert owners == {"tutorial/hooks.py"}, (\n        "tutorial inbox copy must have one owning module; "\n        f"found: {sorted(owners)}"\n    )\n'''
guard_path.write_text(guard, encoding='utf-8')
