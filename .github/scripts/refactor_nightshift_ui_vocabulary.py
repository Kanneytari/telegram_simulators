from __future__ import annotations

from pathlib import Path
import re

ROOT = Path("shadow_market_simulator")
APP = ROOT / "app"
TESTS = ROOT / "tests"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing replacement anchor: {label}")
    return text.replace(old, new, 1)


def replace_function(text: str, name: str, replacement: str) -> str:
    match = re.search(rf"(?m)^def {re.escape(name)}\(", text)
    if not match:
        raise SystemExit(f"function not found: {name}")
    start = match.start()
    nxt = re.search(r"(?m)^(?:@|async def|def|class) ", text[match.end():])
    end = match.end() + nxt.start() if nxt else len(text)
    return text[:start] + replacement.rstrip() + "\n\n" + text[end:]


def ensure_import(path: Path, names: set[str]) -> None:
    if not names:
        return
    text = path.read_text(encoding="utf-8")
    prefix = "from app.presentation.vocabulary import "
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if line.startswith(prefix):
            current = {item.strip() for item in line[len(prefix):].split(",") if item.strip()}
            current |= names
            lines[idx] = prefix + ", ".join(sorted(current))
            path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")
            return
    insert_at = 0
    if lines and lines[0].startswith("from __future__ import"):
        insert_at = 1
        while insert_at < len(lines) and not lines[insert_at].strip():
            insert_at += 1
    lines.insert(insert_at, prefix + ", ".join(sorted(names)))
    path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")


# ---------------------------------------------------------------------------
# Canonical presentation vocabulary.
# ---------------------------------------------------------------------------
presentation = APP / "presentation"
presentation.mkdir(exist_ok=True)
(presentation / "__init__.py").write_text(
    "from .vocabulary import *\n",
    encoding="utf-8",
)
(presentation / "vocabulary.py").write_text(
    '''from __future__ import annotations

from dataclasses import dataclass

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


@dataclass(frozen=True, slots=True)
class UiItem:
    label: str
    callback_data: str


HOME = UiItem("🏠 Меню", "menu:home")
PRODUCT = UiItem("📦 Товар", "menu:product")
SUPPLIERS = UiItem("🤝 Поставщики", "proc:suppliers")
WAREHOUSE = UiItem("📦 Склад", "team:batches")
STOREFRONT = UiItem("🏷 Витрина", "menu:storefront")
TEAM = UiItem("👥 Команда", "menu:team")
ANALYTICS = UiItem("📊 Аналитика", "menu:analytics")
INBOX = UiItem("📨 Входящие", "menu:inbox")
ADMIN = UiItem("🛠 Админ", "admin:panel")
RECRUIT = UiItem("🔎 Нанять", "team:recruit")
PAYMENT = UiItem("⚙️ Оплата", "team:terms")
PACKAGING = UiItem("⚙️ Фасовки", "sales:packaging")
REFRESH = UiItem("🔄 Обновить", "menu:home")


def label(item: UiItem, suffix: object | None = None) -> str:
    return item.label if suffix is None else f"{item.label} · {suffix}"


def button(
    item: UiItem,
    *,
    callback_data: str | None = None,
    suffix: object | None = None,
) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=label(item, suffix),
        callback_data=callback_data or item.callback_data,
    )


def nav_row(
    parent: UiItem | str | None = None,
    parent_text: str | None = None,
    *,
    callback_data: str | None = None,
    menu: bool = True,
) -> list[InlineKeyboardButton]:
    row: list[InlineKeyboardButton] = []
    if isinstance(parent, UiItem):
        row.append(button(parent, callback_data=callback_data))
    elif parent:
        if not parent_text:
            raise ValueError("parent_text is required for a raw callback")
        row.append(InlineKeyboardButton(text=parent_text, callback_data=callback_data or parent))
    if menu:
        row.append(button(HOME))
    return row


def nav(
    parent: UiItem | str | None = None,
    parent_text: str | None = None,
    *,
    callback_data: str | None = None,
    menu: bool = True,
) -> InlineKeyboardMarkup:
    row = nav_row(
        parent,
        parent_text,
        callback_data=callback_data,
        menu=menu,
    )
    return InlineKeyboardMarkup(inline_keyboard=[row] if row else [])
''',
    encoding="utf-8",
)


# ---------------------------------------------------------------------------
# ui_common: formatting/presentation transport only. Remove post-hoc button
# rewriting and move navigation factories into presentation.vocabulary.
# ---------------------------------------------------------------------------
common_path = APP / "ui_common.py"
common = common_path.read_text(encoding="utf-8")
common = common.replace(
    "from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message",
    "from aiogram.types import InlineKeyboardMarkup, Message",
)
common = re.sub(
    r"\n\ndef _normalize_button_text\(text: str\) -> str:.*?\n\nasync def present\(",
    "\n\nasync def present(",
    common,
    flags=re.S,
)
common = common.replace("    markup = _normalize_menu_buttons(markup)\n", "")
common = re.sub(
    r"\n\ndef nav\(.*?\n\ndef notice\(",
    "\n\ndef notice(",
    common,
    flags=re.S,
)
common = common.replace('        .replace("← ", "")\n', "")
common_path.write_text(common, encoding="utf-8")


# Move nav/nav_row imports away from ui_common everywhere.
for path in APP.rglob("*.py"):
    if path == common_path:
        continue
    text = path.read_text(encoding="utf-8")
    match = re.search(r"(?m)^from (?:\.|app\.)ui_common import ([^\n]+)$", text)
    if not match:
        match = re.search(r"(?m)^from \.ui_common import ([^\n]+)$", text)
    if match:
        names = [item.strip() for item in match.group(1).split(",")]
        moved = {name for name in names if name in {"nav", "nav_row"}}
        if moved:
            kept = [name for name in names if name not in moved]
            new_line = "from .ui_common import " + ", ".join(kept)
            text = text[:match.start()] + new_line + text[match.end():]
            path.write_text(text, encoding="utf-8")
            ensure_import(path, moved)

# Explicit old arrows were previously silently removed by ui_common. Make the
# actual source equal the actual UI instead.
for path in APP.rglob("*.py"):
    if path == common_path:
        continue
    text = path.read_text(encoding="utf-8")
    if "← " in text:
        path.write_text(text.replace("← ", ""), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main navigation.
# ---------------------------------------------------------------------------
nav_path = APP / "ui_navigation.py"
nav_text = nav_path.read_text(encoding="utf-8")
nav_text = replace_function(
    nav_text,
    "home_keyboard",
    '''def home_keyboard(opened: int, urgent: int, *, is_admin: bool = False) -> InlineKeyboardMarkup:
    inbox = label(INBOX, opened)
    if urgent:
        inbox += f" · 🔴 {urgent}"
    rows = [
        [InlineKeyboardButton(text=inbox, callback_data=INBOX.callback_data)],
        [button(PRODUCT), button(STOREFRONT)],
        [button(TEAM), button(ANALYTICS)],
    ]
    if is_admin:
        rows.append([button(ADMIN)])
    rows.append([button(REFRESH)])
    return InlineKeyboardMarkup(inline_keyboard=rows)''',
)
nav_text = nav_text.replace(
    'InlineKeyboardButton(text="Обновить", callback_data=f"inbox:page:{page}"),\n        InlineKeyboardButton(text="Меню", callback_data="menu:home"),',
    'button(REFRESH, callback_data=f"inbox:page:{page}"),\n        button(HOME),',
)
nav_text = nav_text.replace(
    'InlineKeyboardButton(text="Входящие", callback_data=back),\n        InlineKeyboardButton(text="Меню", callback_data="menu:home"),',
    'button(INBOX, callback_data=back),\n        button(HOME),',
)
nav_path.write_text(nav_text, encoding="utf-8")
ensure_import(nav_path, {"ADMIN", "ANALYTICS", "HOME", "INBOX", "PRODUCT", "REFRESH", "STOREFRONT", "TEAM", "button", "label"})


# ---------------------------------------------------------------------------
# Commerce.
# ---------------------------------------------------------------------------
commerce_path = APP / "ui_commerce.py"
commerce = commerce_path.read_text(encoding="utf-8")
commerce = replace_function(
    commerce,
    "_product_root_keyboard",
    '''def _product_root_keyboard(batch_count: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button(SUPPLIERS)],
        [button(WAREHOUSE, suffix=batch_count)],
        [button(HOME)],
    ])''',
)
commerce = commerce.replace('rows.append(nav_row("menu:product", "Товар"))', 'rows.append(nav_row(PRODUCT))')
commerce = commerce.replace('rows.append(nav_row("proc:suppliers", "Поставщики"))', 'rows.append(nav_row(SUPPLIERS))')
commerce = commerce.replace('body = "<b>🤝 Поставщики</b>\\n\\nВыберите категорию товара."', 'body = f"<b>{SUPPLIERS.label}</b>\\n\\nВыберите категорию товара."')
commerce = commerce.replace('body = f"<b>📦 Товар</b>\\n\\nСвободно: <b>{money(free_cash)}</b>"', 'body = f"<b>{PRODUCT.label}</b>\\n\\nСвободно: <b>{money(free_cash)}</b>"')
commerce_path.write_text(commerce, encoding="utf-8")
ensure_import(commerce_path, {"HOME", "PRODUCT", "SUPPLIERS", "WAREHOUSE", "button", "nav_row"})


# ---------------------------------------------------------------------------
# Staff + staff handlers.
# ---------------------------------------------------------------------------
staff_path = APP / "ui_staff.py"
staff = staff_path.read_text(encoding="utf-8")
staff = staff.replace(
    'InlineKeyboardButton(text="Нанять", callback_data="team:recruit"),\n        InlineKeyboardButton(text="Оплата", callback_data="team:terms"),',
    'button(RECRUIT),\n        button(PAYMENT),',
)
staff = staff.replace('[InlineKeyboardButton(text="Меню", callback_data="menu:home")]', '[button(HOME)]')
staff = staff.replace('InlineKeyboardButton(text="Товар", callback_data=f"team:batches:{employee_id}")', 'InlineKeyboardButton(text=PRODUCT.label, callback_data=f"team:batches:{employee_id}")')
staff = staff.replace('nav_row("menu:team", "Команда")', 'nav_row(TEAM)')
staff_path.write_text(staff, encoding="utf-8")
ensure_import(staff_path, {"HOME", "PAYMENT", "PRODUCT", "RECRUIT", "TEAM", "button", "nav_row"})

staff_handlers_path = APP / "ui_staff_handlers.py"
staff_handlers = staff_handlers_path.read_text(encoding="utf-8")
staff_handlers = staff_handlers.replace('nav_row("team:batches", "Склад")', 'nav_row(WAREHOUSE)')
staff_handlers_path.write_text(staff_handlers, encoding="utf-8")
ensure_import(staff_handlers_path, {"WAREHOUSE", "nav_row"})


# ---------------------------------------------------------------------------
# Disputes, admin, analytics.
# ---------------------------------------------------------------------------
dispute_path = APP / "ui_disputes.py"
dispute = dispute_path.read_text(encoding="utf-8")
dispute = dispute.replace('nav_row(back, "Входящие")', 'nav_row(INBOX, callback_data=back)')
dispute_path.write_text(dispute, encoding="utf-8")
ensure_import(dispute_path, {"INBOX", "nav_row"})

admin_path = APP / "ui_admin.py"
admin = admin_path.read_text(encoding="utf-8")
admin = admin.replace('[InlineKeyboardButton(text="Меню", callback_data="menu:home")]', '[button(HOME)]')
admin_path.write_text(admin, encoding="utf-8")
ensure_import(admin_path, {"HOME", "button"})

analytics_path = APP / "analytics" / "analytics_handlers.py"
analytics = analytics_path.read_text(encoding="utf-8")
analytics = analytics.replace('[InlineKeyboardButton(text="Меню", callback_data="menu:home")]', '[button(HOME)]')
analytics = analytics.replace('InlineKeyboardButton(text="Меню", callback_data="menu:home")', 'button(HOME)')
analytics_path.write_text(analytics, encoding="utf-8")
ensure_import(analytics_path, {"HOME", "button"})


# Generic canonical replacements for remaining explicit common buttons.
for path in APP.rglob("*.py"):
    if path == presentation / "vocabulary.py":
        continue
    text = path.read_text(encoding="utf-8")
    before = text
    text = text.replace('InlineKeyboardButton(text="Товар",', 'InlineKeyboardButton(text=PRODUCT.label,')
    text = text.replace("InlineKeyboardButton(text='Товар',", "InlineKeyboardButton(text=PRODUCT.label,")
    text = text.replace('InlineKeyboardButton(text="Меню", callback_data="menu:home")', 'button(HOME)')
    text = text.replace("InlineKeyboardButton(text='Меню', callback_data='menu:home')", 'button(HOME)')
    text = text.replace('InlineKeyboardButton(text="Обновить",', 'InlineKeyboardButton(text=REFRESH.label,')
    text = text.replace("InlineKeyboardButton(text='Обновить',", 'InlineKeyboardButton(text=REFRESH.label,')
    if text != before:
        path.write_text(text, encoding="utf-8")
        used: set[str] = set()
        for name in ("PRODUCT", "HOME", "REFRESH", "button"):
            if re.search(rf"\b{re.escape(name)}\b", text):
                used.add(name)
        ensure_import(path, used)


# ---------------------------------------------------------------------------
# Tutorial stage copy: separate copy from state/behavior.
# ---------------------------------------------------------------------------
copy_path = APP / "tutorial" / "copy.py"
copy_path.write_text(
    '''from __future__ import annotations

from app.presentation.vocabulary import ANALYTICS, INBOX, PAYMENT, PRODUCT, RECRUIT, STOREFRONT, TEAM

from .core import (
    CONTINUE_LABEL,
    STAGE_DISPUTE,
    STAGE_HANDOFF,
    STAGE_HANDOFF_WAIT,
    STAGE_PICKUP_WAIT,
    STAGE_PREP_WAIT,
    STAGE_PRICE,
    STAGE_PROCUREMENT,
    STAGE_REVIEW,
    STAGE_SALE_WAIT,
    STAGE_TEAM,
)


RETURN_TO_MENU = "Вернись в Меню, чтобы продолжить обучение"


def instruction(state: dict) -> str:
    stage = state["stage"]
    data = state["data"]
    if stage == STAGE_PROCUREMENT:
        return (
            "Привет, бро! Рад видеть.\n"
            "Поздравляю, теперь у тебя свой шоп.\n\n"
            "Самое время закупиться первой партией товара.\n"
            f"Нажми [{PRODUCT.label}] и выбери стафф, с которого хочешь начать.\n"
            "Обрати внимание на цену, качество и надежность поставки.\n\n"
            "Мы тут не конфеты продаем. Случиться может что угодно.\n"
            "Смотри в оба.\n"
            "Обнял."
        )
    if stage == STAGE_PICKUP_WAIT:
        return (
            "Складмен забирает товар. Обычно это занимает игровое время.\n\n"
            "Можешь заниматься другими делами и дождаться окончания.\n"
            "Если не хочешь ждать, нажми [⏩ Пропустить ожидание]."
        )
    if stage == STAGE_HANDOFF:
        return f"Нажми [{PRODUCT.label}]"
    if stage == STAGE_HANDOFF_WAIT:
        return (
            "Складмен передает товар закладчику.\n\n"
            "Можешь продолжать заниматься магазином и дождаться окончания.\n"
            "Если не хочешь ждать, нажми [⏩ Пропустить ожидание]."
        )
    if stage == STAGE_PREP_WAIT:
        return (
            "Закладчик готовит товар к витрине.\n\n"
            "Можешь дождаться окончания.\n"
            "Если не хочешь ждать, нажми [⏩ Пропустить ожидание]."
        )
    if stage == STAGE_PRICE:
        return f"Нажми [{STOREFRONT.label}]"
    if stage == STAGE_SALE_WAIT:
        return (
            "Теперь дождись первой продажи.\n\n"
            "Можешь продолжать играть как обычно.\n"
            "Если не хочешь ждать, нажми [⏩ Пропустить ожидание]."
        )
    if stage == STAGE_REVIEW:
        order_id = data.get("order_id")
        suffix = f" #{order_id}" if order_id else ""
        return (
            f"Первый заказ{suffix} прошел.\n\n"
            "Выручка еще не равна чистой прибыли. Есть себестоимость товара и выплаты команде.\n\n"
            "После продаж появляются оценки товара и закладчика.\n\n"
            f"Нажми [{CONTINUE_LABEL}], чтобы познакомиться с диспутами."
        )
    if stage == STAGE_DISPUTE:
        return f"Нажми [{INBOX.label}], чтобы открыть первый диспут."
    if stage == STAGE_TEAM:
        return (
            "Перед завершением обучения посмотри остальные разделы.\n\n"
            f"[{TEAM.label}]\n"
            "Проверь сотрудников, их нагрузку, депозит и результаты работы.\n\n"
            f"[{RECRUIT.label}]\n"
            "Ищи новых сотрудников и задавай требования к кандидатам.\n\n"
            f"[{PAYMENT.label}]\n"
            "Настраивай условия выплат для складменов и закладчиков.\n\n"
            "[⚙️ Фасовки]\n"
            "Настраивай, сколько нового товара продавать фасовками по 1, 2 и 5 единиц.\n\n"
            f"[{ANALYTICS.label}]\n"
            "Смотри продажи, расходы и прибыль.\n\n"
            f"[{INBOX.label}]\n"
            "Здесь появляются сообщения и ситуации, которые требуют решения.\n\n"
            "Когда закончишь, нажми [✅ Завершить обучение]."
        )
    return "Обучение завершено."
''',
    encoding="utf-8",
)

core_path = APP / "tutorial" / "core.py"
core = core_path.read_text(encoding="utf-8")
core = re.sub(
    r"\n\ndef _instruction\(state: dict\) -> str:.*?\n\ndef _append_tutorial_action\(",
    "\n\ndef _append_tutorial_action(",
    core,
    flags=re.S,
)
core_path.write_text(core, encoding="utf-8")

hooks_path = APP / "tutorial" / "hooks.py"
hooks = hooks_path.read_text(encoding="utf-8")
hooks = hooks.replace("    _instruction,\n", "")
hooks = hooks.replace("RETURN_TO_MENU = \"Вернись в Меню, чтобы продолжить обучение\"\n\n\n", "")
hooks = hooks.replace("_instruction(state)", "instruction(state)")
hooks = hooks.replace("<b>📦 Товар</b>", "<b>{PRODUCT.label}</b>")
hooks = hooks.replace("<b>🤝 Поставщики</b>", "<b>{SUPPLIERS.label}</b>")
hooks_path.write_text(hooks, encoding="utf-8")
ensure_import(hooks_path, {"PRODUCT", "SUPPLIERS"})
hooks = hooks_path.read_text(encoding="utf-8")
anchor = "from .core import ("
idx = hooks.find(anchor)
if idx < 0:
    raise SystemExit("tutorial hooks import anchor not found")
# Add copy import after the core import block.
end = hooks.find(")\n", idx)
if end < 0:
    raise SystemExit("tutorial hooks core import block end not found")
end += 2
if "from .copy import RETURN_TO_MENU, instruction" not in hooks:
    hooks = hooks[:end] + "from .copy import RETURN_TO_MENU, instruction\n" + hooks[end:]
hooks_path.write_text(hooks, encoding="utf-8")

init_path = APP / "tutorial" / "__init__.py"
init_text = init_path.read_text(encoding="utf-8")
init_text = init_text.replace("    _instruction as _instruction,\n", "")
if "from .copy import instruction" not in init_text:
    init_text += "\nfrom .copy import instruction\n"
init_path.write_text(init_text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Existing tests: expectations should describe source UI directly, not a
# later normalization pass.
# ---------------------------------------------------------------------------
compact_path = TESTS / "test_compact_ui.py"
compact = compact_path.read_text(encoding="utf-8")
compact = compact.replace('"← Товар", "🏠 Меню"', '"📦 Товар", "🏠 Меню"')
compact = compact.replace('"Меню",\n    ]', '"🏠 Меню",\n    ]')
compact_path.write_text(compact, encoding="utf-8")

updates_path = TESTS / "test_zz_gameplay_updates.py"
updates = updates_path.read_text(encoding="utf-8")
updates = updates.replace("    from app.ui_common import _normalize_menu_buttons\n", "    from app.presentation.vocabulary import HOME, button\n")
updates = re.sub(
    r"\n    raw = InlineKeyboardMarkup\(.*?assert _labels\(normalized\) == \[\"🏠 Меню\"\]\n",
    "\n    assert button(HOME).text == \"🏠 Меню\"\n",
    updates,
    flags=re.S,
)
updates_path.write_text(updates, encoding="utf-8")

final_path = TESTS / "test_zzzz_product_ui_final.py"
final = final_path.read_text(encoding="utf-8")
final = final.replace('["Товар", "🏠 Меню"]', '["📦 Товар", "🏠 Меню"]')
final_path.write_text(final, encoding="utf-8")

# Keep expected raw labels aligned after removing hidden arrow normalization.
for path in TESTS.rglob("*.py"):
    text = path.read_text(encoding="utf-8")
    if "← " in text:
        path.write_text(text.replace("← ", ""), encoding="utf-8")


# New permanent contract tests.
(TESTS / "test_ui_vocabulary.py").write_text(
    '''from __future__ import annotations

import ast
from pathlib import Path

from app.presentation.vocabulary import (
    ANALYTICS,
    HOME,
    INBOX,
    PRODUCT,
    STOREFRONT,
    SUPPLIERS,
    TEAM,
    WAREHOUSE,
    button,
)
from app import ui_commerce


APP = Path(__file__).resolve().parents[1] / "app"


def test_canonical_section_vocabulary() -> None:
    assert PRODUCT.label == "📦 Товар"
    assert PRODUCT.callback_data == "menu:product"
    assert SUPPLIERS.label == "🤝 Поставщики"
    assert WAREHOUSE.label == "📦 Склад"
    assert STOREFRONT.label == "🏷 Витрина"
    assert TEAM.label == "👥 Команда"
    assert ANALYTICS.label == "📊 Аналитика"
    assert INBOX.label == "📨 Входящие"
    assert HOME.label == "🏠 Меню"
    assert button(PRODUCT).text == PRODUCT.label


def test_product_back_button_uses_canonical_product_label(monkeypatch) -> None:
    monkeypatch.setattr(ui_commerce, "_stock_status", lambda *_args: "нет запаса")
    markup = ui_commerce._procurement_products_keyboard(
        object(),
        1,
        [{"id": 1, "title": "Амфетамин"}],
    )
    labels = [button.text for row in markup.inline_keyboard for button in row]
    assert labels[-2:] == [PRODUCT.label, HOME.label]


def test_no_post_hoc_button_normalizer_or_hidden_back_arrows() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in APP.rglob("*.py"))
    assert "_normalize_menu_buttons" not in source
    assert "_normalize_button_text" not in source
    assert "← " not in source


def test_plain_product_button_cannot_return() -> None:
    offenders: list[str] = []
    for path in APP.rglob("*.py"):
        if path.name == "vocabulary.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if name != "InlineKeyboardButton":
                continue
            text_kw = next((kw.value for kw in node.keywords if kw.arg == "text"), None)
            if isinstance(text_kw, ast.Constant) and text_kw.value == "Товар":
                offenders.append(f"{path.relative_to(APP)}:{getattr(node, 'lineno', '?')}")
    assert not offenders, f"plain Product button labels found: {offenders}"
''',
    encoding="utf-8",
)


# Architecture docs: document the presentation boundary.
arch_path = ROOT / "docs" / "ARCHITECTURE.md"
arch = arch_path.read_text(encoding="utf-8")
arch = arch.replace(
    "├── tutorial/                # onboarding и гарантии первого игрового цикла\n│\n├── ui_admin.py",
    "├── tutorial/                # onboarding и гарантии первого игрового цикла\n├── presentation/            # канонический UI vocabulary: названия, emoji, callbacks, общая навигация\n│\n├── ui_admin.py",
)
arch = arch.replace(
    "Root `ui_*.py` — единственные разрешённые крупные presentation-модули в корне `app/`.\n\nRouter/renderer отвечает за:",
    "Root `ui_*.py` — единственные разрешённые крупные presentation-модули в корне `app/`.\n\n`presentation/vocabulary.py` владеет повторяемым UI-языком приложения: каноническими названиями разделов, emoji, callback для глобальной навигации и фабриками общих кнопок. Renderer не должен заново придумывать подпись `Товар`, `Меню`, `Команда` и других глобальных разделов. Постфактум-переписывание уже созданной клавиатуры запрещено: правильная подпись должна создаваться сразу.\n\nУникальный динамический текст конкретного экрана остаётся рядом с renderer, чтобы presentation-логика не превращалась в один гигантский словарь. Stage-level onboarding-copy хранится отдельно от tutorial hooks.\n\nRouter/renderer отвечает за:",
)
arch_path.write_text(arch, encoding="utf-8")


# ---------------------------------------------------------------------------
# Static verification before pytest.
# ---------------------------------------------------------------------------
all_app = "\n".join(path.read_text(encoding="utf-8") for path in APP.rglob("*.py"))
for forbidden in ("_normalize_menu_buttons", "_normalize_button_text", "← "):
    if forbidden in all_app:
        raise SystemExit(f"forbidden UI compatibility mechanism remains: {forbidden}")

# No module may still import nav helpers from ui_common.
for path in APP.rglob("*.py"):
    text = path.read_text(encoding="utf-8")
    if re.search(r"from .*ui_common import .*\bnav(?:_row)?\b", text):
        raise SystemExit(f"legacy nav import remains: {path}")

print("UI vocabulary refactor applied")
