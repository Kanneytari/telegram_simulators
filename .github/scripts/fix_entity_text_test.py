from pathlib import Path

ROOT = Path("shadow_market_simulator")
APP = ROOT / "app"
TESTS = ROOT / "tests"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"anchor not found in {path}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


(TESTS / "test_entity_text_consistency.py").write_text('''from pathlib import Path


APP = Path(__file__).resolve().parents[1] / "app"


def test_staff_and_tutorial_role_texts_use_entity_helpers() -> None:
    staff = (APP / "ui_staff.py").read_text(encoding="utf-8")
    handlers = (APP / "ui_staff_handlers.py").read_text(encoding="utf-8")
    tutorial = (APP / "tutorial" / "copy.py").read_text(encoding="utf-8")

    assert "employee_html(snapshot['alias'], 'courier')" in staff
    assert "employee_html(s['alias'], 'courier')" in staff
    assert "role_html(role, plural=True)" in staff
    assert "Выберите {role_html('courier', form='кладмена')}" in handlers
    assert "Сейчас: {role_html(current_role)}" in handlers
    assert "Новая роль: {role_html(new_role)}" in handlers
    assert "role_html('warehouse', capitalize=True)" in tutorial
    assert "role_html('courier', form='закладчику')" in tutorial


def test_analytics_and_operation_results_use_entity_helpers() -> None:
    analytics = (APP / "analytics" / "business_analytics.py").read_text(encoding="utf-8")
    workflow = (APP / "commerce" / "workflow.py").read_text(encoding="utf-8")

    assert 'product_html(row["title"])' in analytics
    assert "employee_html(stressed[0]['alias'], str(stressed[0]['role']))" in analytics
    assert "role_html('courier', plural=True, capitalize=True)" in analytics
    assert "product_html(batch['product_title'])" in workflow
    assert "employee_html(retail['alias'], 'courier')" in workflow
    assert "batch_html(batch_id)" in workflow


def test_numeric_controls_remain_compact() -> None:
    commerce = (APP / "ui_commerce.py").read_text(encoding="utf-8")
    staff = (APP / "ui_staff.py").read_text(encoding="utf-8")
    assert 'text="−5%"' in commerce
    assert 'text="+5%"' in commerce
    assert 'text="−5"' in staff
    assert 'text="+5"' in staff
''', encoding="utf-8")

replace_once(
    TESTS / "test_tutorial_copy_update.py",
    '"После продаж появляются оценки товара и закладчика.\\n\\n"',
    '"После продаж появляются оценки товара и 👤 <b>закладчика</b>.\\n\\n"',
)
replace_once(
    TESTS / "test_tutorial_flow.py",
    'assert "Складмен забирает первую партию" in onboarding["body"], repr(onboarding["body"])',
    'assert "🚚 <b>Складмен</b> забирает первую партию" in onboarding["body"], repr(onboarding["body"])',
)
replace_once(
    TESTS / "test_zz_gameplay_updates.py",
    'assert "Выберите кладмена" in target.text',
    'assert "Выберите 👤 <b>кладмена</b>" in target.text',
)
