from __future__ import annotations

import inspect

from app.courier_idle_handlers import recipient_button_text
from app.workflow_reassign_handlers import build_workflow_reassign_router


def test_live_batch_screen_uses_idle_aware_recipient_label():
    source = inspect.getsource(build_workflow_reassign_router)
    assert "recipient_button_text(employee)" in source


def test_idle_recipient_marker_is_before_employee_name():
    text = recipient_button_text({
        "id": 7,
        "alias": "Крот",
        "deposit": 43_100,
        "exposure": 0,
        "status_text": "свободен",
        "idle_ready": True,
    })
    assert text == "🟢 Крот · депозит 43,100 ₽"
