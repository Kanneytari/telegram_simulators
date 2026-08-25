from __future__ import annotations


MAX_EMPLOYEE_NAME_LENGTH = 24


def normalize_employee_name(raw_name: str) -> str:
    return " ".join((raw_name or "").strip().split())


def rename_employee(game, player_id: int, employee_id: int, raw_name: str) -> dict:
    name = normalize_employee_name(raw_name)
    if not name:
        return {"status": "invalid", "text": "Имя не может быть пустым."}
    if len(name) > MAX_EMPLOYEE_NAME_LENGTH:
        return {
            "status": "invalid",
            "text": f"Имя слишком длинное. Максимум {MAX_EMPLOYEE_NAME_LENGTH} символа.",
        }
    if any(symbol in name for symbol in "<>&"):
        return {
            "status": "invalid",
            "text": "В имени нельзя использовать символы <, > и &.",
        }

    with game.db.connect() as conn:
        employee = conn.execute(
            "SELECT id, alias, active FROM employees WHERE id=? AND player_id=?",
            (employee_id, player_id),
        ).fetchone()
        if not employee or not employee["active"]:
            return {"status": "missing", "text": "Сотрудник больше недоступен."}

        others = conn.execute(
            "SELECT alias FROM employees WHERE player_id=? AND active=1 AND id<>?",
            (player_id, employee_id),
        ).fetchall()
        if any(str(row["alias"]).casefold() == name.casefold() for row in others):
            return {
                "status": "duplicate",
                "text": "В команде уже есть сотрудник с таким именем.",
            }

        old_name = str(employee["alias"])
        if old_name == name:
            return {
                "status": "same",
                "text": "Это уже текущее имя сотрудника.",
                "name": name,
            }

        conn.execute(
            "UPDATE employees SET alias=? WHERE id=? AND player_id=?",
            (name, employee_id, player_id),
        )

    return {
        "status": "renamed",
        "text": f"Сотрудник переименован: {old_name} → {name}.",
        "name": name,
        "old_name": old_name,
    }
