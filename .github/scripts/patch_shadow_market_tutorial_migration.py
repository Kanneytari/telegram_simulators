from pathlib import Path
import re

path = Path('.github/scripts/migrate_shadow_market_tutorial.py')
text = path.read_text(encoding='utf-8')

# Avoid tutorial.core -> engine.simulation -> tutorial.hooks import cycle.
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


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
'''
assert old in text
text = text.replace(old, new, 1)

# Static hooks need every constant referenced by the extracted wrappers.
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

# The old runtime tried to patch analytics through a root compatibility facade.
# Canonical analytics handlers do not expose these symbols, so this hook was not
# part of the active v2 runtime. Do not accidentally introduce new behavior now.
pattern = re.compile(
    r'''\n    app / "analytics/analytics_handlers\.py": \(\n        "from \.\.tutorial import hooks as tutorial_hooks",\n        \{\n            "overview_text": \["handoff_analytics"\],\n            "products_text": \["handoff_analytics"\],\n            "finance_text": \["handoff_analytics"\],\n        \},\n    \),'''
)
text, count = pattern.subn('', text, count=1)
assert count == 1, count

# Release-audit imports a retained constant and a removed installer on one line.
# Teach the migration to preserve the constant while dropping only the installer.
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
        "from app.tutorial import STARTING_FREE_CASH",
    )
    path.write_text(text, encoding="utf-8")
'''
assert needle in text
text = text.replace(needle, replacement, 1)

path.write_text(text, encoding='utf-8')
