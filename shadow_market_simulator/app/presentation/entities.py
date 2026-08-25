from __future__ import annotations

from dataclasses import dataclass
from html import escape


@dataclass(frozen=True, slots=True)
class RoleStyle:
    icon: str
    singular: str
    plural: str


ROLE_STYLES = {
    "courier": RoleStyle("👤", "закладчик", "закладчики"),
    "warehouse": RoleStyle("🚚", "складмен", "складмены"),
}


def role_icon(role: str) -> str:
    return ROLE_STYLES[role].icon


def role_label(role: str, *, plural: bool = False, form: str | None = None, capitalize: bool = False) -> str:
    style = ROLE_STYLES[role]
    name = form if form is not None else (style.plural if plural else style.singular)
    if capitalize:
        name = name[:1].upper() + name[1:]
    return f"{style.icon} {name}"


def role_html(role: str, *, plural: bool = False, form: str | None = None, capitalize: bool = False) -> str:
    style = ROLE_STYLES[role]
    name = form if form is not None else (style.plural if plural else style.singular)
    if capitalize:
        name = name[:1].upper() + name[1:]
    return f"{style.icon} <b>{escape(name)}</b>"


def employee_html(alias: object, role: str) -> str:
    return f"{role_icon(role)} <b>{escape(str(alias or ''))}</b>"


def product_html(title: object) -> str:
    return f"<b>{escape(str(title or ''))}</b>"


def batch_html(batch_id: int) -> str:
    return f"📦 <b>Партия #{int(batch_id)}</b>"
