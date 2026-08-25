from __future__ import annotations


def courier_idle_ready(conn, player_id: int, employee_id: int) -> bool:
    """Return True only for a courier who is completely idle and can take new work now."""
    employee = conn.execute(
        """SELECT id FROM employees
           WHERE id=? AND player_id=? AND active=1 AND available=1 AND role='courier'""",
        (employee_id, player_id),
    ).fetchone()
    if not employee:
        return False

    active_task = conn.execute(
        """SELECT 1 FROM employee_tasks
           WHERE player_id=? AND employee_id=? AND status='active' LIMIT 1""",
        (player_id, employee_id),
    ).fetchone()
    if active_task:
        return False

    pending_or_preparing = conn.execute(
        """SELECT 1 FROM retail_allocations
           WHERE player_id=? AND retail_employee_id=?
             AND status IN ('waiting','preparing') LIMIT 1""",
        (player_id, employee_id),
    ).fetchone()
    if pending_or_preparing:
        return False

    published = conn.execute(
        """SELECT 1 FROM retail_positions
           WHERE player_id=? AND employee_id=? AND position_count>0 LIMIT 1""",
        (player_id, employee_id),
    ).fetchone()
    return not published
