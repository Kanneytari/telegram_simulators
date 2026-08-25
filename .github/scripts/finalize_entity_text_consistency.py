from pathlib import Path

ROOT = Path('shadow_market_simulator')
APP = ROOT / 'app'
TESTS = ROOT / 'tests'


def patch(path: Path, replacements: list[tuple[str, str]]) -> None:
    text = path.read_text(encoding='utf-8')
    for old, new in replacements:
        if old not in text:
            print(f'anchor not found in {path}: {old[:80]!r}')
            continue
        text = text.replace(old, new)
    path.write_text(text, encoding='utf-8')


# Staff screens: employee and role entities use one canonical representation.
patch(APP / 'ui_staff.py', [
    (
        'text = f"<b>Отдых · {clean(snapshot[\'alias\'])}</b>\\n\\nСейчас: {snapshot[\'condition_icon\']} {snapshot[\'condition\']}"',
        'text = f"<b>Отдых</b> · {employee_html(snapshot[\'alias\'], \'courier\')}\\n\\nСейчас: {snapshot[\'condition_icon\']} {snapshot[\'condition\']}"',
    ),
    (
        'f"<b>Развитие · {clean(s[\'alias\'])}</b>\\n\\n"',
        'f"<b>Развитие</b> · {employee_html(s[\'alias\'], \'courier\')}\\n\\n"',
    ),
    (
        'f"<b>Депозит · {clean(s[\'alias\'])}</b>\\n\\n"',
        'f"<b>Депозит</b> · {employee_html(s[\'alias\'], \'courier\')}\\n\\n"',
    ),
    (
        'employee = conn.execute("SELECT alias FROM employees WHERE id=? AND player_id=? AND active=1", (employee_id, player_id)).fetchone()',
        'employee = conn.execute("SELECT alias, role FROM employees WHERE id=? AND player_id=? AND active=1", (employee_id, player_id)).fetchone()',
    ),
    (
        'await present(target, f"<b>{clean(employee[\'alias\'])} · ещё</b>", more_keyboard(employee_id))',
        'await present(target, f"{employee_html(employee[\'alias\'], str(employee[\'role\']))} · <b>Ещё</b>", more_keyboard(employee_id))',
    ),
    (
        'batches_keyboard(rows, f"team:employee:{employee_id}", "Профиль")',
        'batches_keyboard(rows, f"team:employee:{employee_id}", "🚚 Профиль")',
    ),
    (
        'await present(target, f"<b>Сменить складмена</b>\\n\\nПартия #{batch_id} · {money(value)}", InlineKeyboardMarkup(inline_keyboard=rows))',
        'await present(target, f"<b>Сменить</b> · {role_html(\'warehouse\', form=\'складмена\')}\\n\\n📦 <b>Партия #{batch_id}</b> · {money(value)}", InlineKeyboardMarkup(inline_keyboard=rows))',
    ),
    (
        '    title = "закладчики" if role == "courier" else "складмены"\n    text = (\n        f"<b>Оплата · {title}</b>\\n\\n"',
        '    text = (\n        f"<b>Оплата</b> · {role_html(role, plural=True)}\\n\\n"',
    ),
    (
        'text += "\\n\\nДоплата за риск начисляется только на стоимость товара сверх депозита складмена."',
        'text += f"\\n\\nДоплата за риск начисляется только на стоимость товара сверх депозита {role_html(\'warehouse\', form=\'складмена\')}."',
    ),
    (
        'f"<b>{channel.icon} {clean(channel.title)} · {role}</b>\\n\\n"',
        'f"<b>{channel.icon} {clean(channel.title)}</b> · {role}\\n\\n"',
    ),
])

# Staff handlers: role-specific employee rendering must work for both roles.
patch(APP / 'ui_staff_handlers.py', [
    (
        'text += "\\n\\nВыберите кладмена"',
        'text += f"\\n\\nВыберите {role_html(\'courier\', form=\'кладмена\')}"',
    ),
    (
        'body = f"<b>Кандидаты · {len(candidates)}</b>"',
        'body = f"<b>👥 Кандидаты · {len(candidates)}</b>"',
    ),
    (
        '"SELECT alias FROM employees WHERE id=? AND player_id=? AND active=1",',
        '"SELECT alias, role FROM employees WHERE id=? AND player_id=? AND active=1",',
    ),
    (
        'f"<b>Переименовать</b> · 👤 <b>{clean(employee[\'alias\'])}</b>\\n\\nОтправь новое имя. Максимум 24 символа."',
        'f"<b>Переименовать</b> · {employee_html(employee[\'alias\'], str(employee[\'role\']))}\\n\\nОтправь новое имя. Максимум 24 символа."',
    ),
])

# Commerce tips and entity headings.
patch(APP / 'ui_commerce.py', [
    (
        'body = f"<b>📦 {clean(product[\'title\'])}</b>\\n\\nДоступно: {len(offers)} предложений."',
        'body = f"{product_html(product[\'title\'])}\\n\\nДоступно: {len(offers)} предложений."',
    ),
    (
        'text += "\\n\\n💡 Эти доли применяются к товару, который закладчики будут готовить к витрине после следующих передач."',
        'text += f"\\n\\n💡 Эти доли применяются к товару, который {role_html(\'courier\', plural=True)} будут готовить к витрине после следующих передач."',
    ),
])

# Dispute screens: employee/role references stay styled in explanatory copy too.
patch(APP / 'ui_disputes.py', [
    (
        'text += f"\\n\\n<b>Пояснение закладчика</b>\\n{clean(row[\'courier_reply\'])}"',
        'text += f"\\n\\n<b>Пояснение</b> · {role_html(\'courier\')}\\n{clean(row[\'courier_reply\'])}"',
    ),
    (
        'text += "\\n\\nПояснение закладчика не запрошено."',
        'text += f"\\n\\nПояснение {role_html(\'courier\', form=\'закладчика\')} не запрошено."',
    ),
    (
        'InlineKeyboardButton(text=f"💰 Из депозита {context[\'employee_alias\']}",',
        'InlineKeyboardButton(text=f"👤 Из депозита {context[\'employee_alias\']}",',
    ),
    (
        'f"Из депозита {clean(context[\'employee_alias\'])}\\n"',
        'f"Из депозита {employee_html(context[\'employee_alias\'], \'courier\')}\\n"',
    ),
])

# Tutorial copy: role nouns are gameplay entities, including inflected forms.
path = APP / 'tutorial' / 'copy.py'
text = path.read_text(encoding='utf-8')
if 'from app.presentation.entities import role_html' not in text:
    text = text.replace(
        'from app.presentation.vocabulary import ANALYTICS, INBOX, PACKAGING, PAYMENT, PRODUCT, RECRUIT, STOREFRONT, TEAM\n',
        'from app.presentation.entities import role_html\nfrom app.presentation.vocabulary import ANALYTICS, INBOX, PACKAGING, PAYMENT, PRODUCT, RECRUIT, STOREFRONT, TEAM\n',
        1,
    )
text = text.replace(
    '"Складмен забирает товар. Обычно это занимает игровое время.\\n\\n"',
    'f"{role_html(\'warehouse\', capitalize=True)} забирает товар. Обычно это занимает игровое время.\\n\\n"',
)
text = text.replace(
    '"Складмен передает товар закладчику.\\n\\n"',
    'f"{role_html(\'warehouse\', capitalize=True)} передает товар {role_html(\'courier\', form=\'закладчику\')}.\\n\\n"',
)
text = text.replace(
    '"Закладчик готовит товар к витрине.\\n\\n"',
    'f"{role_html(\'courier\', capitalize=True)} готовит товар к витрине.\\n\\n"',
)
text = text.replace(
    '"После продаж появляются оценки товара и закладчика.\\n\\n"',
    'f"После продаж появляются оценки товара и {role_html(\'courier\', form=\'закладчика\')}.\\n\\n"',
)
text = text.replace(
    '"Настраивай условия выплат для складменов и закладчиков.\\n\\n"',
    'f"Настраивай условия выплат для {role_html(\'warehouse\', form=\'складменов\')} и {role_html(\'courier\', form=\'закладчиков\')}.\\n\\n"',
)
path.write_text(text, encoding='utf-8')

# Tutorial runtime copy generated after the first purchase.
path = APP / 'tutorial' / 'hooks.py'
text = path.read_text(encoding='utf-8')
if 'from app.presentation.entities import role_html' not in text:
    text = text.replace(
        'from app.presentation.vocabulary import PRODUCT, STOREFRONT, SUPPLIERS, WAREHOUSE, button\n',
        'from app.presentation.entities import role_html\nfrom app.presentation.vocabulary import PRODUCT, STOREFRONT, SUPPLIERS, WAREHOUSE, button\n',
        1,
    )
old_sql = '''conn.execute(
                    """UPDATE inbox
                       SET body='Складмен забирает первую партию. Обычно это занимает игровое время.'
                       WHERE player_id=? AND kind='tutorial' AND status='open'""",
                    (player_id,),
                )'''
new_sql = '''conn.execute(
                    """UPDATE inbox
                       SET body=?
                       WHERE player_id=? AND kind='tutorial' AND status='open'""",
                    (
                        f"{role_html('warehouse', capitalize=True)} забирает первую партию. Обычно это занимает игровое время.",
                        player_id,
                    ),
                )'''
text = text.replace(old_sql, new_sql)
text = text.replace(
    "tutorial_hint('Складмен забирает товар. Обычно это занимает время. Можешь продолжать играть или вернуться в меню и нажать ⏩ Пропустить ожидание.')",
    "tutorial_hint(f\"{role_html('warehouse', capitalize=True)} забирает товар. Обычно это занимает время. Можешь продолжать играть или вернуться в меню и нажать ⏩ Пропустить ожидание.\")",
)
path.write_text(text, encoding='utf-8')

# Analytics is a player-facing screen too: product, employee and role entities
# use the same canonical representation as operational screens.
path = APP / 'analytics' / 'business_analytics.py'
text = path.read_text(encoding='utf-8')
if 'from ..presentation.entities import employee_html, product_html, role_html' not in text:
    text = text.replace(
        'from html import escape\n\n',
        'from html import escape\n\nfrom ..presentation.entities import employee_html, product_html, role_html\n',
        1,
    )
text = text.replace(
    'return "🟡 Покупатели стали хуже оценивать работу закладчиков."',
    'return f"🟡 Покупатели стали хуже оценивать работу {role_html(\'courier\', form=\'закладчиков\')}."',
)
text = text.replace('title = escape(row["title"])', 'title = product_html(row["title"])')
text = text.replace(
    'f"🔴 {escape(str(stressed[0][\'alias\']))} работает на пределе — риск ошибок и срыва выше."',
    'f"🔴 {employee_html(stressed[0][\'alias\'], str(stressed[0][\'role\']))} работает на пределе — риск ошибок и срыва выше."',
)
text = text.replace(
    'f"🟡 У {escape(str(stressed[0][\'alias\']))} высокий стресс; стоит проверить нагрузку."',
    'f"🟡 У {employee_html(stressed[0][\'alias\'], str(stressed[0][\'role\']))} высокий стресс; стоит проверить нагрузку."',
)
text = text.replace(
    'f"🟡 Оценка работы закладчиков снизилась до {current[\'courier_rating\']:.1f}/5."',
    'f"🟡 Оценка работы {role_html(\'courier\', form=\'закладчиков\')} снизилась до {current[\'courier_rating\']:.1f}/5."',
)
text = text.replace(
    'f"🟢 {escape(row[\'title\'])} продаётся заметно лучше прошлого периода."',
    'f"🟢 {product_html(row[\'title\'])} продаётся заметно лучше прошлого периода."',
)
text = text.replace(
    'f"Закладчики: {_rating_with_trend(current[\'courier_rating\'], current[\'rating_count\'], previous[\'courier_rating\'], previous[\'rating_count\'], ready)}\\n"',
    'f"{role_html(\'courier\', plural=True, capitalize=True)}: {_rating_with_trend(current[\'courier_rating\'], current[\'rating_count\'], previous[\'courier_rating\'], previous[\'rating_count\'], ready)}\\n"',
)
text = text.replace(
    'f"{icon} <b>{escape(row[\'title\'])}</b>\\n"',
    'f"{icon} {product_html(row[\'title\'])}\\n"',
)
path.write_text(text, encoding='utf-8')

# Player-facing service result strings also need the same entity vocabulary.
path = APP / 'commerce' / 'workflow.py'
text = path.read_text(encoding='utf-8')
if 'from ..presentation.entities import batch_html, employee_html, product_html, role_html' not in text:
    text = text.replace(
        'from ..tutorial import hooks as tutorial_hooks\n',
        'from ..presentation.entities import batch_html, employee_html, product_html, role_html\nfrom ..tutorial import hooks as tutorial_hooks\n',
        1,
    )
text = text.replace(
    'f"Складмен: <b>{employee[\'alias\']}</b>\\n"',
    'f"{role_html(\'warehouse\', capitalize=True)}: {employee_html(employee[\'alias\'], \'warehouse\')}\\n"',
)
text = text.replace(
    '"Оплата за работу будет начислена после передачи товара закладчику."',
    'f"Оплата за работу будет начислена после передачи товара {role_html(\'courier\', form=\'закладчику\')}."',
)
text = text.replace(
    'return "Закладчик недоступен."',
    'return f"{role_html(\'courier\', capitalize=True)} недоступен."',
)
text = text.replace(
    'warning = f"\\n\\n🔴 После получения у закладчика будет не покрыто депозитом: {unsecured:,} ₽." if unsecured else ""',
    'warning = f"\\n\\n🔴 После получения у {role_html(\'courier\', form=\'закладчика\')} будет не покрыто депозитом: {unsecured:,} ₽." if unsecured else ""',
)
text = text.replace(
    'f"Назначено <b>{quantity} ед.</b> {batch[\'product_title\']} сотруднику {retail[\'alias\']}.\\n\\n"\n            f"{batch[\'wholesale_alias\']} начал подготовку передачи. После завершения {retail[\'alias\']} автоматически начнёт подготовку товара к витрине.{warning}"',
    'f"Назначено <b>{quantity} ед.</b> {product_html(batch[\'product_title\'])} сотруднику {employee_html(retail[\'alias\'], \'courier\')}.\\n\\n"\n            f"{employee_html(batch[\'wholesale_alias\'], \'warehouse\')} начал подготовку передачи. После завершения {employee_html(retail[\'alias\'], \'courier\')} автоматически начнёт подготовку товара к витрине.{warning}"',
)
text = text.replace(
    'return f"Партия #{batch_id} закреплена за {employee[\'alias\']}.{warning}"',
    'return f"{batch_html(batch_id)} закреплена за {employee_html(employee[\'alias\'], \'warehouse\')}.{warning}"',
)
text = text.replace(
    '        role_title = "складмен" if new_role == "warehouse" else "закладчик"\n        return f"{employee[\'alias\']} переведён в роль «{role_title}»."',
    '        return f"{employee_html(employee[\'alias\'], new_role)} переведён в роль {role_html(new_role)}."',
)
path.write_text(text, encoding='utf-8')

# Focused permanent regression checks: semantic entity styling is required in
# high-value player-facing text, while local numeric controls stay compact.
(TESTS / 'test_entity_text_consistency.py').write_text('''from pathlib import Path\n\n\nAPP = Path(__file__).resolve().parents[1] / "app"\n\n\ndef test_staff_and_tutorial_role_texts_use_entity_helpers() -> None:\n    staff = (APP / "ui_staff.py").read_text(encoding="utf-8")\n    handlers = (APP / "ui_staff_handlers.py").read_text(encoding="utf-8")\n    tutorial = (APP / "tutorial" / "copy.py").read_text(encoding="utf-8")\n\n    assert "employee_html(snapshot['alias'], 'courier')" in staff\n    assert "employee_html(s['alias'], 'courier')" in staff\n    assert "role_html(role, plural=True)" in staff\n    assert "Выберите {role_html('courier', form='кладмена')}" in handlers\n    assert "Сейчас: {role_html(current_role)}" in handlers\n    assert "Новая роль: {role_html(new_role)}" in handlers\n    assert "role_html('warehouse', capitalize=True)" in tutorial\n    assert "role_html('courier', form='закладчику')" in tutorial\n\n\ndef test_analytics_and_operation_results_use_entity_helpers() -> None:\n    analytics = (APP / "analytics" / "business_analytics.py").read_text(encoding="utf-8")\n    workflow = (APP / "commerce" / "workflow.py").read_text(encoding="utf-8")\n\n    assert "product_html(row[\"title\"])" in analytics\n    assert "employee_html(stressed[0]['alias'], str(stressed[0]['role']))" in analytics\n    assert "role_html('courier', plural=True, capitalize=True)" in analytics\n    assert "product_html(batch['product_title'])" in workflow\n    assert "employee_html(retail['alias'], 'courier')" in workflow\n    assert "batch_html(batch_id)" in workflow\n\n\ndef test_numeric_controls_remain_compact() -> None:\n    commerce = (APP / "ui_commerce.py").read_text(encoding="utf-8")\n    staff = (APP / "ui_staff.py").read_text(encoding="utf-8")\n    assert 'text="−5%"' in commerce\n    assert 'text="+5%"' in commerce\n    assert 'text="−5"' in staff\n    assert 'text="+5"' in staff\n''', encoding='utf-8')

print('final entity text consistency applied')
