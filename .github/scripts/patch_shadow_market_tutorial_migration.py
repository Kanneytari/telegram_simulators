from pathlib import Path
import re

path = Path('.github/scripts/migrate_shadow_market_tutorial.py')
text = path.read_text(encoding='utf-8')

# Avoid tutorial.core -> engine.simulation -> tutorial.hooks import cycle and
# make tutorial behavior an explicit Database runtime capability.
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

# Static hooks need every constant referenced by the extracted wrappers, plus
# the opt-in runtime predicate.
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

# Every static hook is a no-op unless the Database was explicitly enabled by
# application composition. This preserves normal engine semantics in unit tests
# and other consumers while removing runtime monkey-patching.
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

# Add generic runtime DB discovery to hooks. It handles service methods and UI
# renderers without introducing a global flag.
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

# The old runtime tried to patch analytics through a root compatibility facade.
# Canonical analytics handlers do not expose these symbols, so this hook was not
# part of the active v2 runtime. Do not accidentally introduce new behavior now.
pattern = re.compile(
    r'''\n    app / "analytics/analytics_handlers\.py": \(\n        "from \.\.tutorial import hooks as tutorial_hooks",\n        \{\n            "overview_text": \["handoff_analytics"\],\n            "products_text": \["handoff_analytics"\],\n            "finance_text": \["handoff_analytics"\],\n        \},\n    \),'''
)
text, count = pattern.subn('', text, count=1)
assert count == 1, count

# Bootstrap composes tutorial behavior explicitly, but no longer installs or
# mutates functions/classes at runtime.
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

# Release-audit imports a retained constant and a removed installer on one line.
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

# Fix and modernize the tests that intentionally exercise the production
# onboarding runtime. All other tests keep the runtime disabled and therefore
# retain the ordinary starter-state contract.
marker = 'path = tests / "test_architecture_guardrails.py"\n'
assert marker in text
specific = r'''
# Tutorial flow: replace installer setup with explicit runtime composition and
# repair historical indentation in the embedded script.
path = tests / "test_tutorial_flow.py"
body = path.read_text(encoding="utf-8")
body = body.replace("                from app.tutorial import (", "        from app.tutorial import (")
body = body.replace("                            import app.tutorial as tutorial", "        import app.tutorial as tutorial")
body = body.replace("        import app.tutorial as tutorial", "        import app.tutorial as tutorial")
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

# Nonblocking tutorial now validates the single final canonical copy instead of
# an intermediate pre-copy-update overlay state.
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

# Copy test imports the canonical value directly; there is no installer anymore.
path = tests / "test_tutorial_copy_update.py"
body = path.read_text(encoding="utf-8")
body = body.replace(
    "        from app.tutorial_copy_update import CONTINUE_LABEL, apply_tutorial_copy_update\n",
    "        from app.tutorial import CONTINUE_LABEL\n",
)
body = body.replace("        apply_tutorial_copy_update()\n\n", "")
path.write_text(body, encoding="utf-8")

# Release audit opts into the exact production tutorial composition.
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

path.write_text(text, encoding='utf-8')
