from __future__ import annotations

import subprocess
import sys
import textwrap


def test_tutorial_copy_uses_blocks_and_exact_button_labels() -> None:
    script = textwrap.dedent(
        r'''
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        from app import tutorial
        from app.tutorial_copy_update import CONTINUE_LABEL, apply_tutorial_copy_update
        from app.ui_common import tutorial_hint


        apply_tutorial_copy_update()

        review = tutorial._instruction(
            {"stage": tutorial.STAGE_REVIEW, "data": {"order_id": 1}}
        )
        assert review == (
            "Первый заказ #1 прошел.\n\n"
            "Выручка еще не равна чистой прибыли. Есть себестоимость товара и выплаты команде.\n\n"
            "После продаж появляются оценки товара и закладчика.\n\n"
            "Нажми [▶️ Продолжить обучение], чтобы познакомиться с диспутами."
        )
        assert "[Продолжить обучение, чтобы" not in review

        markup = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="🏠 Меню", callback_data="menu:home")
            ]]
        )
        updated = tutorial._append_tutorial_action(
            markup,
            {"stage": tutorial.STAGE_REVIEW, "data": {}},
        )
        continue_buttons = [
            button
            for row in updated.inline_keyboard
            for button in row
            if button.callback_data == "tutorial:continue"
        ]
        assert len(continue_buttons) == 1
        assert continue_buttons[0].text == CONTINUE_LABEL

        formatted = tutorial_hint(
            "Первая мысль. Вторая мысль. Нажми ⏩ Пропустить ожидание."
        )
        assert "Первая мысль.\n\nВторая мысль.\n\n" in formatted
        assert "[⏩ Пропустить ожидание]" in formatted

        for stage in (
            tutorial.STAGE_PROCUREMENT,
            tutorial.STAGE_PICKUP_WAIT,
            tutorial.STAGE_HANDOFF_WAIT,
            tutorial.STAGE_PREP_WAIT,
            tutorial.STAGE_SALE_WAIT,
            tutorial.STAGE_REVIEW,
            tutorial.STAGE_TEAM,
        ):
            text = tutorial._instruction({"stage": stage, "data": {}})
            assert "\n\n" in text

        assert tutorial._instruction(
            {"stage": tutorial.STAGE_HANDOFF, "data": {}}
        ) == "Нажми [📦 Товар]"
        assert tutorial._instruction(
            {"stage": tutorial.STAGE_PRICE, "data": {}}
        ) == "Нажми [🏷 Витрина]"
        '''
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
