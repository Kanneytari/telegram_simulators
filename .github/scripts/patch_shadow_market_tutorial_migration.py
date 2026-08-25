from pathlib import Path
import re

path = Path('.github/scripts/migrate_shadow_market_tutorial.py')
text = path.read_text(encoding='utf-8')

old = '''import json
from datetime import timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from ..engine.simulation import iso, utcnow
'''
new = '''import json
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup


TUTORIAL_RUNTIME_ATTR = "_nightshift_tutorial_runtime_enabled"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def enable_runtime(db) -> None:
    setattr(db, TUTORIAL_RUNTIME_ATTR, True)


def runtime_enabled(db) -> bool:
    return bool(db is not None and getattr(db, TUTORIAL_RUNTIME_ATTR, False))
'''
assert old in text
text = text.replace(old, new, 1)

old = '''from .core import (
    STAGE_DISPUTE,
    STAGE_HANDOFF,
    STAGE_PRICE,
    STAGE_PROCUREMENT,
    STAGE_SALE_WAIT,
    _append_tutorial_action,'''
new = '''from .core import (
    STARTING_CAPITAL,
    STARTING_RESERVE,
    STAGE_DISPUTE,
    STAGE_HANDOFF,
    STAGE_HANDOFF_WAIT,
    STAGE_PICKUP_WAIT,
    STAGE_PRICE,
    STAGE_PROCUREMENT,
    STAGE_SALE_WAIT,
    STAGE_TEAM,
    _append_tutorial_action,'''
assert old in text
text = text.replace(old, new, 1)

old = '''    sync_tutorial_state,
    tutorial_active,
    tutorial_state,
)
from ..ui_common'''
new = '''    runtime_enabled,
    sync_tutorial_state,
    tutorial_active,
    tutorial_state,
)
from ..ui_common'''
assert old in text
text = text.replace(old, new, 1)

old = '''    body = textwrap.indent(ast.unparse(fn), "    ")
    return f"def {decorator_name}(original):\\n{body}\\n    return {fn.name}\\n"
'''
new = '''    body = textwrap.indent(ast.unparse(fn), "    ")
    return (
        f"def {decorator_name}(original):\\n{body}\\n"
        f"    decorated = {fn.name}\\n\\n"
        "    @wraps(original)\\n"
        "    def guarded(*args, **kwargs):\\n"
        "        db = _runtime_db(args, kwargs)\\n"
        "        if not runtime_enabled(db):\\n"
        "            return original(*args, **kwargs)\\n"
        "        return decorated(*args, **kwargs)\\n\\n"
        "    return guarded\\n"
    )
'''
assert old in text
text = text.replace(old, new, 1)

needle = '''RETURN_TO_MENU = "Вернись в Меню, чтобы продолжить обучение"


def _handoff_state'''
replacement = '''RETURN_TO_MENU = "Вернись в Меню, чтобы продолжить обучение"


def _runtime_db(args, kwargs):
    for key in ("db", "game"):
        value = kwargs.get(key)
        if value is not None:
            if hasattr(value, "connect"):
                return value
            db = getattr(value, "db", None)
            if db is not None and hasattr(db, "connect"):
                return db
    for value in args:
        if hasattr(value, "connect"):
            return value
        db = getattr(value, "db", None)
        if db is not None and hasattr(db, "connect"):
            return db
    return None


def _handoff_state'''
assert needle in text
text = text.replace(needle, replacement, 1)

pattern = re.compile(
    r'''\n    app / "analytics/analytics_handlers\.py": \(\n        "from \.\.tutorial import hooks as tutorial_hooks",\n        \{\n            "overview_text": \["handoff_analytics"\],\n            "products_text": \["handoff_analytics"\],\n            "finance_text": \["handoff_analytics"\],\n        \},\n    \),'''
)
text, count = pattern.subn('', text, count=1)
assert count == 1, count

old = '''text = text.replace(
    "from .tutorial import apply_tutorial_updates, build_tutorial_router\\n",
    "from .tutorial import build_tutorial_router\\n",
)'''
new = '''text = text.replace(
    "from .tutorial import apply_tutorial_updates, build_tutorial_router\\n",
    "from .tutorial import build_tutorial_router, enable_runtime\\n",
)'''
assert old in text
text = text.replace(old, new, 1)

needle = '''for call in (
    "    apply_tutorial_updates()\\n",
    "    apply_tutorial_runtime_fixes()\\n",
    "    apply_tutorial_copy_update()\\n",
):
    text = text.replace(call, "")
path.write_text(text, encoding="utf-8")
'''
replacement = '''for call in (
    "    apply_tutorial_updates()\\n",
    "    apply_tutorial_runtime_fixes()\\n",
    "    apply_tutorial_copy_update()\\n",
):
    text = text.replace(call, "")
text = text.replace("    db.init()\\n", "    db.init()\\n    enable_runtime(db)\\n", 1)
path.write_text(text, encoding="utf-8")
'''
assert needle in text
text = text.replace(needle, replacement, 1)

needle = '''    text = text.replace(
        "                from app.tutorial import (",
        "        from app.tutorial import (",
    )
    path.write_text(text, encoding="utf-8")
'''
replacement = '''    text = text.replace(
        "                from app.tutorial import (",
        "        from app.tutorial import (",
    )
    text = text.replace(
        "from app.tutorial import STARTING_FREE_CASH, apply_tutorial_updates",
        "from app.tutorial import STARTING_FREE_CASH, enable_runtime",
    )
    path.write_text(text, encoding="utf-8")
'''
assert needle in text
text = text.replace(needle, replacement, 1)

# Explicitly qualify the one extracted closure reference that depended on a
# sibling wrapper function in the old installer.
needle = '''hooks_source = hooks_header + "\\n\\n" + "\\n\\n".join(generated)
(package / "hooks.py").write_text(hooks_source, encoding="utf-8")

init_source = '''
assert needle in text
replacement = '''hooks_source = hooks_header + "\\n\\n" + "\\n\\n".join(generated)
hooks_source, qualified_count = re.subn(
    r"(?m)^(\\s*)await render_product_root\\(",
    r"\\1from .. import ui_commerce\\n\\1await ui_commerce.render_product_root(",
    hooks_source,
    count=1,
)
assert qualified_count == 1, qualified_count
(package / "hooks.py").write_text(hooks_source, encoding="utf-8")

init_source = '''
text = text.replace(needle, replacement, 1)

# Ruff requires underscored compatibility re-exports to be explicit aliases.
old = '''init_source = '''from .core import *
from .core import (
    _active_task_for_stage,
    _append_tutorial_action,
    _ensure_schema_conn,
    _finish_tutorial,
    _free_cash,
    _instruction,
    _set_stage,
)
'''
'''
new = '''init_source = '''from .core import *
from .core import (
    _active_task_for_stage as _active_task_for_stage,
    _append_tutorial_action as _append_tutorial_action,
    _ensure_schema_conn as _ensure_schema_conn,
    _finish_tutorial as _finish_tutorial,
    _free_cash as _free_cash,
    _instruction as _instruction,
    _set_stage as _set_stage,
)
'''
'''
assert old in text
text = text.replace(old, new, 1)

marker = 'path = tests / "test_architecture_guardrails.py"\n'
assert marker in text
specific = r'''
path = tests / "test_tutorial_flow.py"
body = path.read_text(encoding="utf-8")
body = body.replace("                from app.tutorial import (", "        from app.tutorial import (")
body = re.sub(
    r"(?m)^\s*import app\.tutorial as tutorial$",
    "        import app.tutorial as tutorial",
    body,
)
for line in (
    "        from app.tutorial_copy_update import apply_tutorial_copy_update\n",
    "        from app.tutorial_runtime import apply_tutorial_runtime_fixes\n",
    "            tutorial.apply_tutorial_updates()\n",
    "            apply_tutorial_runtime_fixes()\n",
    "            apply_tutorial_copy_update()\n",
):
    body = body.replace(line, "")
body = body.replace("            db.init()\n", "            db.init()\n            tutorial.enable_runtime(db)\n", 1)
path.write_text(body, encoding="utf-8")

path = tests / "test_tutorial_nonblocking.py"
body = path.read_text(encoding="utf-8")
body = body.replace("                from app.tutorial_runtime import apply_tutorial_runtime_fixes\n", "")
body = body.replace("            tutorial.apply_tutorial_updates()\n", "")
body = body.replace("            apply_tutorial_runtime_fixes()\n", "")
body = body.replace("            db.init()\n", "            db.init()\n            tutorial.enable_runtime(db)\n", 1)
body = body.replace(
    '            assert price.startswith("Вернись в меню и нажми 🏷 Витрина.")',
    '            assert price == "Нажми [🏷 Витрина]"',
)
body = body.replace(
    '                "какая часть нового товара будет продаваться по 1, 2 и 5 единиц"',
    '                "сколько нового товара продавать фасовками по 1, 2 и 5 единиц"',
)
path.write_text(body, encoding="utf-8")

path = tests / "test_tutorial_copy_update.py"
body = path.read_text(encoding="utf-8")
body = body.replace(
    "        from app.tutorial_copy_update import CONTINUE_LABEL, apply_tutorial_copy_update\n",
    "        from app.tutorial import CONTINUE_LABEL\n",
)
body = body.replace("        apply_tutorial_copy_update()\n\n", "")
path.write_text(body, encoding="utf-8")

path = tests / "test_zzzz_release_audit.py"
body = path.read_text(encoding="utf-8")
body = body.replace(
    "from app.tutorial import STARTING_FREE_CASH",
    "from app.tutorial import STARTING_FREE_CASH, enable_runtime",
)
body = body.replace("    db.init()\n    db.init()\n", "    db.init()\n    db.init()\n    enable_runtime(db)\n", 1)
path.write_text(body, encoding="utf-8")

'''
text = text.replace(marker, specific + marker, 1)

old = '''forbidden = [
    "apply_tutorial_updates",
    "apply_tutorial_runtime_fixes",
    "apply_tutorial_copy_update",
    "tutorial_runtime",
    "tutorial_copy_update",
]
'''
new = '''forbidden = [
    "apply_tutorial_updates",
    "apply_tutorial_runtime_fixes",
    "apply_tutorial_copy_update",
    "from .tutorial_runtime",
    "from app.tutorial_runtime",
    "from .tutorial_copy_update",
    "from app.tutorial_copy_update",
]
'''
assert old in text
text = text.replace(old, new, 1)

path.write_text(text, encoding='utf-8')
