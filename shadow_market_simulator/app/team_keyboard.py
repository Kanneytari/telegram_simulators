from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _clean_status(status: str | None) -> str:
    value = (status or "").strip()
    if value.lower() == "свободен":
        return ""
    prefix = "свободен · "
    if value.lower().startswith(prefix):
        return value[len(prefix):].strip()
    return value


def employee_list(employees) -> InlineKeyboardMarkup:
    rows = []
    for employee in employees:
        role_icon = "🚚" if employee["role"] == "warehouse" else "👤"
        is_mapping = isinstance(employee, dict)
        status = _clean_status(employee.get("status_text") if is_mapping else None)
        exposure = int(employee.get("exposure", 0)) if is_mapping else 0
        deposit = int(employee["deposit"])
        idle_ready = bool(employee.get("idle_ready", False)) if is_mapping else False

        if exposure > deposit:
            marker = " 🔴"
        elif employee["role"] == "courier" and idle_ready:
            marker = " 🟢"
        else:
            marker = ""

        label = f"{role_icon} {employee['alias']} · {deposit:,} ₽"
        if status:
            label += f" · {status}"
        label += marker
        rows.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"employee:{employee['id']}",
            )
        ])

    rows.extend([
        [InlineKeyboardButton(text="💰 Условия работы", callback_data="team:terms")],
        [
            InlineKeyboardButton(text="🔎 Набор", callback_data="recruit:menu"),
            InlineKeyboardButton(text="⚙️ Фасовки", callback_data="team:packrules"),
        ],
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data="menu:team"),
            InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
        ],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)
