from __future__ import annotations

import subprocess
import sys
import textwrap


def test_tutorial_copy_uses_blocks_and_exact_button_labels() -> None:
    script = textwrap.dedent(
        r'''
        import inspect

        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        from app import tutorial, ui_navigation
        from app.tutorial import CONTINUE_LABEL
        from app.ui_common import normalize_text, tutorial_hint


        
        intro = tutorial.instruction(
            {"stage": tutorial.STAGE_PROCUREMENT, "data": {}}
        )
        assert intro == (
            "Привет, бро! Рад видеть.\n"
            "Поздравляю, теперь у тебя свой шоп.\n\n"
            "Самое время закупиться первой партией товара.\n"
            "Нажми [📦 Товар] и выбери стафф, с которого хочешь начать.\n"
            "Обрати внимание на цену, качество и надежность поставки.\n\n"
            "Мы тут не конфеты продаем. Случиться может что угодно.\n"
            "Смотри в оба.\n"
            "Обнял."
        )
        assert "Привет, бро!\n\nРад видеть." not in tutorial_hint(intro)

        review = tutorial.instruction(
            {"stage": tutorial.STAGE_REVIEW, "data": {"order_id": 1}}
        )
        assert review == (
            "Первый заказ #1 прошел.\n\n"
            "Выручка еще не равна чистой прибыли. Есть себестоимость товара и выплаты команде.\n\n"
            "После продаж появляются оценки товара и 👤 <b>закладчика</b>.\n\n"
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
            "Первая мысль. Вторая мысль.\n\nНажми ⏩ Пропустить ожидание."
        )
        assert "Первая мысль. Вторая мысль.\n\n" in formatted
        assert "Первая мысль.\n\nВторая мысль." not in formatted
        assert "[⏩ Пропустить ожидание]" in formatted

        route_hint = tutorial_hint(
            "Открой «Товар» → «Склад» и распредели товар между закладчиками. "
            "После подготовки фасовки появятся на витрине и начнут продаваться автоматически."
        )
        assert "Открой [Товар], затем [Склад]" in route_hint
        for forbidden in ("—", "«", "»", "→", "←"):
            assert forbidden not in route_hint

        normalized = normalize_text("Текст — тест. «Товар» → «Склад»")
        for forbidden in ("—", "«", "»", "→", "←"):
            assert forbidden not in normalized

        source = inspect.getsource(ui_navigation._home_snapshot)
        assert "Стафф уже на складе!" not in source
        assert "tutorial_hint" not in source

        for stage in (
            tutorial.STAGE_PROCUREMENT,
            tutorial.STAGE_PICKUP_WAIT,
            tutorial.STAGE_HANDOFF_WAIT,
            tutorial.STAGE_PREP_WAIT,
            tutorial.STAGE_SALE_WAIT,
            tutorial.STAGE_REVIEW,
            tutorial.STAGE_TEAM,
        ):
            text = tutorial.instruction({"stage": stage, "data": {}})
            assert "\n\n" in text
            for forbidden in ("—", "«", "»", "→", "←"):
                assert forbidden not in text

        assert tutorial.instruction(
            {"stage": tutorial.STAGE_HANDOFF, "data": {}}
        ) == "Нажми [📦 Товар]"
        assert tutorial.instruction(
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
