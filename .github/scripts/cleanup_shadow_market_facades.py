from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path

ROOT = Path("shadow_market_simulator")
APP = ROOT / "app"
TESTS = ROOT / "tests"

FACADES = {
    "analytics_handlers": "analytics.analytics_handlers",
    "analytics_log": "analytics.analytics_log",
    "business_analytics": "analytics.business_analytics",
    "compensation": "staff.compensation",
    "config": "core.config",
    "courier_core": "staff.couriers.core",
    "courier_idle": "staff.couriers.idle",
    "courier_management": "staff.couriers.management",
    "courier_model": "staff.couriers.model",
    "courier_recruitment": "staff.couriers.recruitment",
    "customer_trust": "trust.customer",
    "db": "core.database",
    "dispute_payments": "disputes.payments",
    "employee_rename": "staff.rename",
    "game": "core.game",
    "global_packaging": "commerce.packaging",
    "inbox_lifecycle": "inbox.lifecycle",
    "nightshift": "engine.timers",
    "operations": "commerce.inventory",
    "procurement_market": "commerce.procurement",
    "recruitment": "staff.recruitment",
    "runtime": "engine.player_time",
    "simulation": "engine.simulation",
    "staff_idle": "staff.idle",
    "staff_insights": "staff.insights",
    "staff_relationships": "staff.relationships",
    "workflow": "commerce.workflow",
}

CANONICAL = {f"app.{old}": f"app.{new}" for old, new in FACADES.items()}


def assert_facade_only(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    forbidden = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    bad = [node for node in tree.body if isinstance(node, forbidden)]
    if bad:
        names = [getattr(node, "name", type(node).__name__) for node in bad]
        raise SystemExit(f"refusing to delete non-facade {path}: {names}")


def module_package(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        return ".".join(parts[:-1])
    return ".".join(parts[:-1])


def rewrite_relative_imports(path: Path, text: str) -> str:
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return text
    package = module_package(path)
    lines = text.splitlines(keepends=True)
    replacements: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level <= 0:
            continue
        try:
            absolute = importlib.util.resolve_name(
                "." * node.level + (node.module or ""), package
            )
        except (ImportError, ValueError):
            continue
        target = CANONICAL.get(absolute)
        if not target:
            continue
        names = ", ".join(
            alias.name + (f" as {alias.asname}" if alias.asname else "")
            for alias in node.names
        )
        indent = " " * node.col_offset
        replacements.append(
            (node.lineno - 1, (node.end_lineno or node.lineno), f"{indent}from {target} import {names}\n")
        )
    for start, end, replacement in sorted(replacements, reverse=True):
        lines[start:end] = [replacement]
    return "".join(lines)


def rewrite_from_app_imports(path: Path, text: str) -> str:
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return text
    lines = text.splitlines(keepends=True)
    replacements: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level != 0 or node.module != "app":
            continue
        legacy = [alias for alias in node.names if alias.name in FACADES]
        if not legacy:
            continue
        keep = [alias for alias in node.names if alias.name not in FACADES]
        indent = " " * node.col_offset
        output: list[str] = []
        if keep:
            names = ", ".join(
                alias.name + (f" as {alias.asname}" if alias.asname else "")
                for alias in keep
            )
            output.append(f"{indent}from app import {names}\n")
        for alias in legacy:
            local_name = alias.asname or alias.name
            output.append(f"{indent}import app.{FACADES[alias.name]} as {local_name}\n")
        replacements.append((node.lineno - 1, (node.end_lineno or node.lineno), "".join(output)))
    for start, end, replacement in sorted(replacements, reverse=True):
        lines[start:end] = [replacement]
    return "".join(lines)


def rewrite_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    original = text
    for old, new in CANONICAL.items():
        text = text.replace(f"from {old} import", f"from {new} import")
        text = text.replace(f"import {old} as ", f"import {new} as ")
        text = re.sub(
            rf"(?m)^([ \t]*)import {re.escape(old)}$",
            rf"\1import {new}",
            text,
        )
    if path.suffix == ".py":
        text = rewrite_from_app_imports(path, text)
        if path == APP / "__init__.py" or APP in path.parents:
            text = rewrite_relative_imports(path, text)
    if text != original:
        path.write_text(text, encoding="utf-8")


for old in FACADES:
    path = APP / f"{old}.py"
    if not path.exists():
        raise SystemExit(f"expected compatibility facade is missing before cleanup: {path}")
    assert_facade_only(path)

text_roots = [APP, TESTS, ROOT / "docs"]
for base in text_roots:
    for path in base.rglob("*"):
        if path.is_file() and path.suffix in {".py", ".md", ".yml", ".yaml"}:
            rewrite_file(path)
rewrite_file(ROOT / "README.md")

compat_test = TESTS / "test_package_compatibility.py"
if compat_test.exists():
    compat_test.unlink()

for old in FACADES:
    (APP / f"{old}.py").unlink()

guardrail = TESTS / "test_architecture_guardrails.py"
text = guardrail.read_text(encoding="utf-8")
start = text.index("ALLOWED_FLAT_MODULES = {")
end = text.index("}\n\n# Existing runtime overlays", start) + 1
allowed = [
    "__init__.py",
    "bootstrap.py",
    "main.py",
    "ui_admin.py",
    "ui_commerce.py",
    "ui_common.py",
    "ui_disputes.py",
    "ui_navigation.py",
    "ui_staff.py",
    "ui_staff_handlers.py",
]
block = "ALLOWED_FLAT_MODULES = {\n" + "".join(f'    "{name}",\n' for name in allowed) + "}"
text = text[:start] + block + text[end:]
guardrail.write_text(text, encoding="utf-8")

status = ROOT / "docs" / "ARCHITECTURE_STATUS.md"
status_text = status.read_text(encoding="utf-8")
status_text = status_text.replace(
    "Large legacy files in the root of `app/` that correspond to these domains are compatibility facades. New production code must import the canonical package path, not add behavior to those facades.\n",
    "Legacy root compatibility facades have been removed. Production code and tests import canonical package paths directly.\n",
)
status_text = re.sub(
    r"## Compatibility policy\n.*?## Validation policy",
    "## Compatibility policy\n\nThe temporary root compatibility layer has been removed. Old import paths are intentionally unsupported inside this application; architecture guardrails prevent those facade modules from returning.\n\n## Validation policy",
    status_text,
    flags=re.S,
)
status_text = re.sub(
    r"## Remaining work\n.*\Z",
    "## Remaining work\n\nThe architecture-v2 structural migration is complete for the active runtime. Future changes should extend the canonical feature packages directly rather than recreating root facades, runtime overlays, or one-class-per-feature inheritance layers.\n",
    status_text,
    flags=re.S,
)
status.write_text(status_text, encoding="utf-8")

scan_files = [*APP.rglob("*.py"), *TESTS.rglob("*.py")]
leftovers: list[str] = []
for path in scan_files:
    body = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(body, filename=str(path))
    except SyntaxError:
        tree = None
    for old in FACADES:
        patterns = (f"from app.{old} import", f"import app.{old}")
        if any(pattern in body for pattern in patterns):
            leftovers.append(f"{path}: app.{old}")
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "app":
                for alias in node.names:
                    if alias.name in FACADES:
                        leftovers.append(f"{path}: from app import {alias.name}")
if leftovers:
    raise SystemExit("legacy facade imports remain:\n" + "\n".join(sorted(set(leftovers))))

Path(".github/scripts/cleanup_shadow_market_facades.py").unlink(missing_ok=True)
Path(".github/workflows/shadow-market-facade-cleanup.yml").unlink(missing_ok=True)
