from pathlib import Path
import re

init = Path("shadow_market_simulator/app/tutorial/__init__.py")
text = init.read_text(encoding="utf-8")
for name in (
    "_active_task_for_stage",
    "_append_tutorial_action",
    "_ensure_schema_conn",
    "_finish_tutorial",
    "_free_cash",
    "_instruction",
    "_set_stage",
):
    old = f"    {name},\n"
    new = f"    {name} as {name},\n"
    assert old in text, name
    text = text.replace(old, new, 1)
init.write_text(text, encoding="utf-8")

hooks = Path("shadow_market_simulator/app/tutorial/hooks.py")
text = hooks.read_text(encoding="utf-8")
text, count = re.subn(
    r"(?m)^(\s*)await render_product_root\(",
    r"\1from .. import ui_commerce\n\1await ui_commerce.render_product_root(",
    text,
    count=1,
)
assert count == 1, count
hooks.write_text(text, encoding="utf-8")

Path(__file__).unlink()
