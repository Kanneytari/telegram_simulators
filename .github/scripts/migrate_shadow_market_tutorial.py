from __future__ import annotations

import ast
import copy
import re
import textwrap
from pathlib import Path

root = Path("shadow_market_simulator")
app = root / "app"
tests = root / "tests"

tutorial_text = (app / "tutorial.py").read_text(encoding="utf-8")
runtime_text = (app / "tutorial_runtime.py").read_text(encoding="utf-8")
copy_text = (app / "tutorial_copy_update.py").read_text(encoding="utf-8")
tutorial_tree = ast.parse(tutorial_text)
runtime_tree = ast.parse(runtime_text)
copy_tree = ast.parse(copy_text)

Func = (ast.FunctionDef, ast.AsyncFunctionDef)


def top_function(tree: ast.Module, name: str):
    matches = [node for node in tree.body if isinstance(node, Func) and node.name == name]
    assert len(matches) == 1, (name, len(matches))
    return copy.deepcopy(matches[0])


def nested_function(tree: ast.Module, installer: str, name: str):
    outer = top_function(tree, installer)
    matches = [
        node
        for node in ast.walk(outer)
        if isinstance(node, Func) and node.name == name and node is not outer
    ]
    assert len(matches) == 1, (installer, name, len(matches))
    return copy.deepcopy(matches[0])


class RenameNames(ast.NodeTransformer):
    def __init__(self, mapping):
        self.mapping = mapping

    def visit_Name(self, node):
        if node.id in self.mapping:
            return ast.copy_location(ast.Name(id=self.mapping[node.id], ctx=node.ctx), node)
        return node


class TutorialAttrsToNames(ast.NodeTransformer):
    def visit_Attribute(self, node):
        node = self.generic_visit(node)
        if isinstance(node.value, ast.Name) and node.value.id == "tutorial":
            return ast.copy_location(ast.Name(id=node.attr, ctx=node.ctx), node)
        return node


class ContinueCopy(ast.NodeTransformer):
    def visit_Constant(self, node):
        if node.value == "Продолжить обучение":
            return ast.copy_location(ast.Constant(value="▶️ Продолжить обучение"), node)
        return node


class RouterImports(ast.NodeTransformer):
    def visit_ImportFrom(self, node):
        if node.module == "ui_disputes" and node.level == 1:
            node.level = 2
        return node


def unparse_function(node) -> str:
    ast.fix_missing_locations(node)
    return ast.unparse(node)


final_instruction = top_function(copy_tree, "_instruction")
final_instruction = TutorialAttrsToNames().visit(final_instruction)
append_action = top_function(tutorial_tree, "_append_tutorial_action")
append_action = ContinueCopy().visit(append_action)
router = top_function(tutorial_tree, "build_tutorial_router")
router = RouterImports().visit(router)
router.body.insert(
    0,
    ast.ImportFrom(module=None, names=[ast.alias(name="ui_navigation")], level=2),
)

core_functions = [
    top_function(tutorial_tree, "_ensure_schema_conn"),
    top_function(tutorial_tree, "tutorial_state"),
    top_function(tutorial_tree, "tutorial_active"),
    top_function(tutorial_tree, "_set_stage"),
    top_function(tutorial_tree, "_finish_tutorial"),
    top_function(tutorial_tree, "_free_cash"),
    final_instruction,
    append_action,
    top_function(tutorial_tree, "_active_task_for_stage"),
    top_function(tutorial_tree, "sync_tutorial_state"),
    top_function(tutorial_tree, "skip_tutorial_wait"),
    top_function(tutorial_tree, "create_tutorial_dispute"),
    router,
]

core_header = """from __future__ import annotations

import json
from datetime import timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from ..engine.simulation import iso, utcnow


STARTING_FREE_CASH = 500_000
STARTING_RESERVE = 30_000
STARTING_CAPITAL = STARTING_FREE_CASH + STARTING_RESERVE

STAGE_PROCUREMENT = "procurement"
STAGE_PICKUP_WAIT = "pickup_wait"
STAGE_HANDOFF = "handoff"
STAGE_HANDOFF_WAIT = "handoff_wait"
STAGE_PREP_WAIT = "prep_wait"
STAGE_PRICE = "price"
STAGE_SALE_WAIT = "sale_wait"
STAGE_REVIEW = "review"
STAGE_DISPUTE = "dispute"
STAGE_TEAM = "team"
STAGE_COMPLETE = "complete"

WAIT_STAGES = {
    STAGE_PICKUP_WAIT,
    STAGE_HANDOFF_WAIT,
    STAGE_PREP_WAIT,
    STAGE_SALE_WAIT,
}

CONTINUE_LABEL = "▶️ Продолжить обучение"
"""
core_source = core_header + "\n\n" + "\n\n\n".join(
    unparse_function(fn) for fn in core_functions
) + "\n"

package = app / "tutorial"
package.mkdir(exist_ok=True)
(package / "core.py").write_text(core_source, encoding="utf-8")


def decorator_source(decorator_name, tree, installer, nested, closure_name):
    fn = nested_function(tree, installer, nested)
    fn = RenameNames({closure_name: "original"}).visit(fn)
    fn.decorator_list = [
        ast.Call(
            func=ast.Name(id="wraps", ctx=ast.Load()),
            args=[ast.Name(id="original", ctx=ast.Load())],
            keywords=[],
        )
    ]
    refs = {node.id for node in ast.walk(fn) if isinstance(node, ast.Name)}
    modules = sorted(refs & {"ui_commerce", "ui_navigation", "ui_staff"})
    for module in reversed(modules):
        fn.body.insert(
            0,
            ast.ImportFrom(module=None, names=[ast.alias(name=module)], level=2),
        )
    ast.fix_missing_locations(fn)
    body = textwrap.indent(ast.unparse(fn), "    ")
    return f"def {decorator_name}(original):\n{body}\n    return {fn.name}\n"


specs = [
    ("new_player_setup", tutorial_tree, "_install_new_player_setup", "ensure_player", "original"),
    ("first_purchase_protection", tutorial_tree, "_install_first_purchase_protection", "buy_offer_for_employee", "original"),
    ("handoff_progress", tutorial_tree, "_install_handoff_progress", "allocate_to_retail", "original"),
    ("price_progress", tutorial_tree, "_install_price_progress", "change_listing_price", "original"),
    ("management_event_protection", tutorial_tree, "_install_random_event_protection", "protected_events", "original_events"),
    ("dispute_probability_protection", tutorial_tree, "_install_random_event_protection", "protected_dispute", "original_dispute"),
    ("dispute_progress", tutorial_tree, "_install_dispute_progress", "resolve_dispute_with_source", "original"),
    ("handoff_tutorial_flag", tutorial_tree, "_install_handoff_tutorial_flag", "needs_first_handoff_tutorial", "original"),
    ("soft_home", tutorial_tree, "_install_soft_guidance_renderers", "render_home", "original_home"),
    ("soft_product_root", tutorial_tree, "_install_soft_guidance_renderers", "render_product_root", "original_product_root"),
    ("soft_procurement_product", tutorial_tree, "_install_soft_guidance_renderers", "render_procurement_product", "original_procurement_product"),
    ("soft_storefront", tutorial_tree, "_install_soft_guidance_renderers", "render_storefront_root", "original_storefront"),
    ("soft_sales_product", tutorial_tree, "_install_soft_guidance_renderers", "render_sales_product", "original_sales_product"),
    ("soft_listing", tutorial_tree, "_install_soft_guidance_renderers", "render_listing", "original_listing"),
    ("copy_rules", runtime_tree, "_install_copy_rules", "ensure_player", "current"),
    ("affordable_empty_product_root", runtime_tree, "_install_procurement_empty_state", "render_product_root", "current_root"),
    ("affordable_empty_procurement_product", runtime_tree, "_install_procurement_empty_state", "render_procurement_product", "current_product"),
    ("handoff_product_root", runtime_tree, "_install_handoff_guidance", "render_product_root", "current_product_root"),
    ("handoff_procurement_product", runtime_tree, "_install_handoff_guidance", "render_procurement_product", "current_product"),
    ("handoff_storefront", runtime_tree, "_install_handoff_guidance", "render_storefront_root", "current_storefront"),
    ("handoff_sales_product", runtime_tree, "_install_handoff_guidance", "render_sales_product", "current_sales_product"),
    ("handoff_listing", runtime_tree, "_install_handoff_guidance", "render_listing", "current_listing"),
    ("handoff_inbox", runtime_tree, "_install_handoff_guidance", "render_inbox", "current_inbox"),
    ("handoff_team", runtime_tree, "_install_handoff_guidance", "render_team", "current_team"),
    ("first_batch_quality_protection", runtime_tree, "_install_first_batch_quality_protection", "buy_offer_for_employee", "current"),
]

hooks_header = """from __future__ import annotations

from functools import wraps

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from . import core as tutorial
from .core import (
    STAGE_DISPUTE,
    STAGE_HANDOFF,
    STAGE_PRICE,
    STAGE_PROCUREMENT,
    STAGE_SALE_WAIT,
    _append_tutorial_action,
    _ensure_schema_conn,
    _free_cash,
    _instruction,
    _set_stage,
    sync_tutorial_state,
    tutorial_active,
    tutorial_state,
)
from ..ui_common import clean, money, notice, present, rating, tutorial_hint


RETURN_TO_MENU = "Вернись в Меню, чтобы продолжить обучение"


def _handoff_state(db, player_id: int) -> bool:
    state = sync_tutorial_state(db, player_id)
    return bool(state and state["active"] and state["stage"] == STAGE_HANDOFF)


class _HintTarget:
    def __init__(self, target, hint: str):
        self._target = target
        self._hint = hint
        self.photo = getattr(target, "photo", None)

    def _text(self, text: str) -> str:
        return f"{text}\\n\\n{self._hint}"

    async def edit_text(self, text, **kwargs):
        return await self._target.edit_text(self._text(text), **kwargs)

    async def answer(self, text, **kwargs):
        return await self._target.answer(self._text(text), **kwargs)

    async def delete(self):
        delete = getattr(self._target, "delete", None)
        if delete is not None:
            return await delete()
        return None


def _return_target(target):
    return _HintTarget(target, tutorial_hint(RETURN_TO_MENU))
"""

generated = [
    decorator_source(name, tree, installer, nested, closure)
    for name, tree, installer, nested, closure in specs
]
generated.append("""def handoff_analytics(original):
    @wraps(original)
    def render_analytics(db, player_id: int, period: str):
        text = original(db, player_id, period)
        if _handoff_state(db, player_id):
            text += "\\n\\n" + tutorial_hint(RETURN_TO_MENU)
        return text

    return render_analytics
""")
hooks_source = hooks_header + "\n\n" + "\n\n".join(generated)
(package / "hooks.py").write_text(hooks_source, encoding="utf-8")

init_source = """from .core import *
from .core import (
    _active_task_for_stage,
    _append_tutorial_action,
    _ensure_schema_conn,
    _finish_tutorial,
    _free_cash,
    _instruction,
    _set_stage,
)
"""
(package / "__init__.py").write_text(init_source, encoding="utf-8")


def add_import(path: Path, import_line: str) -> None:
    text = path.read_text(encoding="utf-8")
    if import_line in text:
        return
    marker = "from __future__ import annotations\n"
    assert marker in text, path
    text = text.replace(marker, marker + "\n" + import_line + "\n", 1)
    path.write_text(text, encoding="utf-8")


def decorate(path: Path, function_name: str, decorators: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, Func) and node.name == function_name
    ]
    assert len(matches) == 1, (path, function_name, len(matches))
    node = matches[0]
    first_line = min([node.lineno] + [item.lineno for item in node.decorator_list])
    lines = text.splitlines(keepends=True)
    indent = re.match(r"\s*", lines[first_line - 1]).group(0)
    insertion = "".join(f"{indent}@tutorial_hooks.{name}\n" for name in decorators)
    lines.insert(first_line - 1, insertion)
    path.write_text("".join(lines), encoding="utf-8")


targets = {
    app / "engine/simulation.py": (
        "from ..tutorial import hooks as tutorial_hooks",
        {"ensure_player": ["copy_rules", "new_player_setup"]},
    ),
    app / "commerce/procurement.py": (
        "from ..tutorial import hooks as tutorial_hooks",
        {"buy_offer_for_employee": ["first_batch_quality_protection", "first_purchase_protection"]},
    ),
    app / "commerce/workflow.py": (
        "from ..tutorial import hooks as tutorial_hooks",
        {
            "allocate_to_retail": ["handoff_progress"],
            "needs_first_handoff_tutorial": ["handoff_tutorial_flag"],
        },
    ),
    app / "core/game.py": (
        "from ..tutorial import hooks as tutorial_hooks",
        {"change_listing_price": ["price_progress"]},
    ),
    app / "staff/couriers/core.py": (
        "from ...tutorial import hooks as tutorial_hooks",
        {
            "_simulate_management_events": ["management_event_protection"],
            "_dispute_probability": ["dispute_probability_protection"],
        },
    ),
    app / "disputes/payments.py": (
        "from ..tutorial import hooks as tutorial_hooks",
        {"resolve_dispute_with_source": ["dispute_progress"]},
    ),
    app / "ui_navigation.py": (
        "from .tutorial import hooks as tutorial_hooks",
        {
            "render_home": ["soft_home"],
            "render_inbox": ["handoff_inbox"],
        },
    ),
    app / "ui_commerce.py": (
        "from .tutorial import hooks as tutorial_hooks",
        {
            "render_product_root": ["handoff_product_root", "affordable_empty_product_root", "soft_product_root"],
            "render_procurement_product": ["handoff_procurement_product", "affordable_empty_procurement_product", "soft_procurement_product"],
            "render_storefront_root": ["handoff_storefront", "soft_storefront"],
            "render_sales_product": ["handoff_sales_product", "soft_sales_product"],
            "render_listing": ["handoff_listing", "soft_listing"],
        },
    ),
    app / "ui_staff.py": (
        "from .tutorial import hooks as tutorial_hooks",
        {"render_team": ["handoff_team"]},
    ),
    app / "analytics/analytics_handlers.py": (
        "from ..tutorial import hooks as tutorial_hooks",
        {
            "overview_text": ["handoff_analytics"],
            "products_text": ["handoff_analytics"],
            "finance_text": ["handoff_analytics"],
        },
    ),
}
for path, (import_line, funcs) in targets.items():
    add_import(path, import_line)
    for function_name, decorators in funcs.items():
        decorate(path, function_name, decorators)

path = app / "bootstrap.py"
text = path.read_text(encoding="utf-8")
text = text.replace(
    "from .tutorial import apply_tutorial_updates, build_tutorial_router\n",
    "from .tutorial import build_tutorial_router\n",
)
text = text.replace("from .tutorial_copy_update import apply_tutorial_copy_update\n", "")
text = text.replace("from .tutorial_runtime import apply_tutorial_runtime_fixes\n", "")
for call in (
    "    apply_tutorial_updates()\n",
    "    apply_tutorial_runtime_fixes()\n",
    "    apply_tutorial_copy_update()\n",
):
    text = text.replace(call, "")
path.write_text(text, encoding="utf-8")

replacements = [
    "from app.tutorial_copy_update import apply_tutorial_copy_update\n",
    "from app.tutorial_runtime import apply_tutorial_runtime_fixes\n",
    "from app.tutorial import apply_tutorial_updates\n",
]
call_patterns = [
    "tutorial.apply_tutorial_updates()\n",
    "apply_tutorial_updates()\n",
    "apply_tutorial_runtime_fixes()\n",
    "apply_tutorial_copy_update()\n",
]
for path in tests.glob("*.py"):
    text = path.read_text(encoding="utf-8")
    for item in replacements:
        text = text.replace(item, "")
    for item in call_patterns:
        text = text.replace(item, "")
    text = re.sub(r"(?m)^\s*apply_tutorial_updates,\s*\n", "", text)
    text = text.replace(
        "                from app.tutorial import (",
        "        from app.tutorial import (",
    )
    path.write_text(text, encoding="utf-8")

path = tests / "test_architecture_guardrails.py"
text = path.read_text(encoding="utf-8")
for name in ("tutorial.py", "tutorial_copy_update.py", "tutorial_runtime.py"):
    text = text.replace(f'    "{name}",\n', "")
text = re.sub(
    r"LEGACY_OVERLAY_MODULES = \{.*?\}\n\n",
    "LEGACY_OVERLAY_MODULES: set[str] = set()\n\n",
    text,
    flags=re.S,
)
path.write_text(text, encoding="utf-8")

(app / "tutorial.py").unlink()
(app / "tutorial_runtime.py").unlink()
(app / "tutorial_copy_update.py").unlink()

status = root / "docs/ARCHITECTURE_STATUS.md"
text = status.read_text(encoding="utf-8")
text = re.sub(
    r"## Runtime overlays\n.*?## Compatibility policy",
    """## Runtime overlays

Runtime overlay debt is now zero.

Removed completely:

- `release_fixes.py`;
- `handoff_copy_update.py`;
- `product_ui_update.py`;
- `gameplay_updates.py`;
- `tutorial.py` as a runtime installer;
- `tutorial_runtime.py`;
- `tutorial_copy_update.py`.

Onboarding now lives in `app/tutorial/`. Tutorial state and flow are in `core.py`; cross-cutting first-cycle behavior is attached explicitly through static decorators in `hooks.py`. `app/bootstrap.py` does not install or mutate tutorial behavior at runtime.

No runtime overlay module is allowed by the architecture guardrail.

## Compatibility policy""",
    text,
    flags=re.S,
)
text = re.sub(
    r"## Remaining work\n.*",
    """## Remaining work

Architecture-v2 structural migration is complete for the active runtime. Remaining root compatibility facades may be removed later only when no production code, tests or external imports depend on them; they are not a second implementation layer and do not install runtime behavior.
""",
    text,
    flags=re.S,
)
status.write_text(text, encoding="utf-8")

Path(".github/workflows/shadow-market-refactor-edit.yml").unlink()
Path(".github/scripts/migrate_shadow_market_tutorial.py").unlink()

forbidden = [
    "apply_tutorial_updates",
    "apply_tutorial_runtime_fixes",
    "apply_tutorial_copy_update",
    "tutorial_runtime",
    "tutorial_copy_update",
]
offenders = []
for path in app.rglob("*.py"):
    body = path.read_text(encoding="utf-8")
    if any(token in body for token in forbidden):
        offenders.append(str(path))
assert not offenders, offenders
assert not (app / "tutorial.py").exists()
assert (app / "tutorial/core.py").exists()
assert (app / "tutorial/hooks.py").exists()
