from pathlib import Path

hooks = Path('shadow_market_simulator/app/tutorial/hooks.py')
text = hooks.read_text(encoding='utf-8')
old_start = "body='Склад пуст. Начни с первой закупки в разделе «Товар».'"
new_start = "body='Сейчас у тебя нет товара. Начни с первой закупки в разделе «Товар».'"
if old_start not in text:
    raise SystemExit('starter inbox copy not found')
text = text.replace(old_start, new_start, 1)

copy_start = text.index('\ndef copy_rules(original):')
copy_end = text.index('\ndef affordable_empty_product_root(original):', copy_start)
text = text[:copy_start] + '\n' + text[copy_end:]

old_purchase = """        if batch:\n            _set_stage(self.db, player_id, STAGE_PICKUP_WAIT, batch_id=int(batch['id']), product_id=int(batch['product_id']), warehouse_employee_id=employee_id)\n            result += '\\n\\n' + tutorial_hint('Складмен забирает товар. Обычно это занимает время. Можешь продолжать играть или вернуться в меню и нажать ⏩ Пропустить ожидание.')\n"""
new_purchase = """        if batch:\n            _set_stage(self.db, player_id, STAGE_PICKUP_WAIT, batch_id=int(batch['id']), product_id=int(batch['product_id']), warehouse_employee_id=employee_id)\n            with self.db.connect() as conn:\n                conn.execute(\n                    \"\"\"UPDATE inbox\n                       SET body='Складмен забирает первую партию. Обычно это занимает игровое время.'\n                       WHERE player_id=? AND kind='tutorial' AND status='open'\"\"\",\n                    (player_id,),\n                )\n            result += '\\n\\n' + tutorial_hint('Складмен забирает товар. Обычно это занимает время. Можешь продолжать играть или вернуться в меню и нажать ⏩ Пропустить ожидание.')\n"""
if old_purchase not in text:
    raise SystemExit('first purchase tutorial block not found')
text = text.replace(old_purchase, new_purchase, 1)
hooks.write_text(text, encoding='utf-8')

simulation = Path('shadow_market_simulator/app/engine/simulation.py')
text = simulation.read_text(encoding='utf-8')
decorator = '    @tutorial_hooks.copy_rules\n'
if decorator not in text:
    raise SystemExit('copy_rules decorator not found')
text = text.replace(decorator, '', 1)
simulation.write_text(text, encoding='utf-8')

insights = Path('shadow_market_simulator/app/staff/insights.py')
text = insights.read_text(encoding='utf-8')
old_insight_copy = """            if created:\n                conn.execute(\n                    \"\"\"UPDATE inbox\n                       SET title='Первая смена',\n                           body='Склад пуст. Начни с первой закупки в разделе Товар.'\n                       WHERE player_id=? AND kind='tutorial' AND status='open'\"\"\",\n                    (player_id,),\n                )\n"""
if old_insight_copy not in text:
    raise SystemExit('staff insight tutorial copy block not found')
text = text.replace(old_insight_copy, '', 1)
insights.write_text(text, encoding='utf-8')

test = Path('shadow_market_simulator/tests/test_tutorial_flow.py')
text = test.read_text(encoding='utf-8')
old_assert = '                assert onboarding and "Склад пуст" in onboarding["body"]\n'
new_assert = '                assert onboarding, "tutorial inbox missing"\n                assert "Сейчас у тебя нет товара" in onboarding["body"], repr(onboarding["body"])\n                assert "Склад пуст" not in onboarding["body"], repr(onboarding["body"])\n'
if old_assert not in text:
    raise SystemExit('starter tutorial assertion not found')
text = text.replace(old_assert, new_assert, 1)
old_batch = """                batch = conn.execute(\n                    \"SELECT status FROM batches WHERE id=? AND player_id=?\",\n                    (batch_id, player_id),\n                ).fetchone()\n                assert batch and batch[\"status\"] == \"receiving\"\n"""
new_batch = """                batch = conn.execute(\n                    \"SELECT status FROM batches WHERE id=? AND player_id=?\",\n                    (batch_id, player_id),\n                ).fetchone()\n                assert batch and batch[\"status\"] == \"receiving\"\n                onboarding = conn.execute(\n                    \"\"\"SELECT body FROM inbox\n                       WHERE player_id=? AND kind='tutorial' AND status='open'\"\"\",\n                    (player_id,),\n                ).fetchone()\n                assert onboarding, \"tutorial inbox missing after purchase\"\n                assert \"Складмен забирает первую партию\" in onboarding[\"body\"], repr(onboarding[\"body\"])\n                assert \"Склад пуст\" not in onboarding[\"body\"], repr(onboarding[\"body\"])\n"""
if old_batch not in text:
    raise SystemExit('receiving batch assertion block not found')
text = text.replace(old_batch, new_batch, 1)
test.write_text(text, encoding='utf-8')

leftovers = []
for path in Path('shadow_market_simulator/app').rglob('*.py'):
    for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if 'Склад пуст' in line or 'copy_rules' in line:
            leftovers.append(f'{path}:{lineno}: {line.strip()}')
if leftovers:
    raise SystemExit('stale tutorial copy sources remain:\n' + '\n'.join(leftovers))
