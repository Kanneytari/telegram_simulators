from pathlib import Path

ROOT = Path('shadow_market_simulator/tests')

compact_path = ROOT / 'test_compact_ui.py'
compact = compact_path.read_text(encoding='utf-8')
compact = compact.replace(
    '    assert labels(markup) == ["Амфетамин", "Кокаин", "← Товар"]\n'
    '    assert callbacks(markup) == ["proc:product:1", "proc:product:3", "menu:product"]\n',
    '    assert labels(markup) == ["Амфетамин", "Кокаин", "← Товар", "🏠 Меню"]\n'
    '    assert callbacks(markup) == [\n'
    '        "proc:product:1", "proc:product:3", "menu:product", "menu:home"\n'
    '    ]\n',
    1,
)
compact_path.write_text(compact, encoding='utf-8')

updates_path = ROOT / 'test_zz_gameplay_updates.py'
updates = updates_path.read_text(encoding='utf-8')
old = '''    assert procurement_labels[len(EXPECTED_PRODUCTS)].startswith("📦 Склад · ")
    assert not any(label.startswith("🚚 Склад") for label in procurement_labels)
    assert procurement_labels[-1] == "🏠 Меню"
'''
new = '''    assert procurement_labels[len(EXPECTED_PRODUCTS)] == "← Товар"
    assert procurement_labels[-1] == "🏠 Меню"
    assert not any(label.startswith("📦 Склад") for label in procurement_labels)

    product_root = ui_commerce._product_root_keyboard(
        ui_commerce._warehouse_batch_count(db, PLAYER_ID)
    )
    product_root_labels = _labels(product_root)
    assert product_root_labels[0] == "🤝 Поставщики"
    assert product_root_labels[1].startswith("📦 Склад · ")
    assert product_root_labels[-1] == "🏠 Меню"
    assert not any(label.startswith("🚚 Склад") for label in product_root_labels)
'''
if old not in updates:
    raise SystemExit('gameplay procurement contract not found')
updates = updates.replace(old, new, 1)
updates_path.write_text(updates, encoding='utf-8')

final_path = ROOT / 'test_zzzz_product_ui_final.py'
final = final_path.read_text(encoding='utf-8')
old = '''    assert any(label.startswith("📦 Склад · ") for label in labels)
    assert not any(label.startswith("🚚 Склад") for label in labels)

    target = Target()
    asyncio.run(ui_commerce.render_product_root(target, db, game, PLAYER_ID))
    assert "<blockquote>Нажми на кнопку [📦 Склад]</blockquote>" in target.text
'''
new = '''    assert labels[len(products)] == "← Товар"
    assert labels[-1] == "🏠 Меню"
    assert not any(label.startswith("📦 Склад") for label in labels)

    product_root = ui_commerce._product_root_keyboard(
        ui_commerce._warehouse_batch_count(db, PLAYER_ID)
    )
    root_labels = [button.text for row in product_root.inline_keyboard for button in row]
    assert root_labels[0] == "🤝 Поставщики"
    assert root_labels[1].startswith("📦 Склад · ")
    assert root_labels[-1] == "🏠 Меню"
    assert not any(label.startswith("🚚 Склад") for label in root_labels)

    suppliers_target = Target()
    asyncio.run(ui_commerce.render_suppliers_root(suppliers_target, db, game, PLAYER_ID))
    supplier_screen_labels = [
        button.text
        for row in suppliers_target.reply_markup.inline_keyboard
        for button in row
    ]
    assert supplier_screen_labels[: len(products)] == product_labels
    assert supplier_screen_labels[-2:] == ["Товар", "🏠 Меню"]

    target = Target()
    asyncio.run(ui_commerce.render_product_root(target, db, game, PLAYER_ID))
    rendered_root_labels = [
        button.text for row in target.reply_markup.inline_keyboard for button in row
    ]
    assert rendered_root_labels[0] == "🤝 Поставщики"
    assert any(label.startswith("📦 Склад · ") for label in rendered_root_labels)
    assert "<blockquote>Нажми на кнопку [📦 Склад]</blockquote>" in target.text
'''
if old not in final:
    raise SystemExit('final product contract not found')
final = final.replace(old, new, 1)
final_path.write_text(final, encoding='utf-8')
