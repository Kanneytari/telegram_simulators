from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from . import tutorial


CONTINUE_LABEL = "▶️ Продолжить обучение"


def _instruction(state: dict) -> str:
    stage = state["stage"]
    data = state["data"]

    if stage == tutorial.STAGE_PROCUREMENT:
        return (
            "Привет, бро! Рад видеть.\n\n"
            "Поздравляю, теперь у тебя свой шоп.\n\n"
            "Самое время закупиться первой партией товара.\n\n"
            "Нажми [📦 Товар] и выбери стафф, с которого хочешь начать.\n\n"
            "Обрати внимание на цену, качество и надежность поставки.\n\n"
            "Мы тут не конфеты продаем. Случиться может что угодно.\n\n"
            "Смотри в оба.\n\n"
            "Обнял."
        )

    if stage == tutorial.STAGE_PICKUP_WAIT:
        return (
            "Складмен забирает товар.\n\n"
            "Обычно это занимает игровое время.\n\n"
            "Можешь заниматься другими делами и дождаться окончания.\n\n"
            "Если не хочешь ждать, нажми [⏩ Пропустить ожидание]."
        )

    if stage == tutorial.STAGE_HANDOFF:
        return "Нажми [📦 Товар]"

    if stage == tutorial.STAGE_HANDOFF_WAIT:
        return (
            "Складмен передает товар закладчику.\n\n"
            "Можешь продолжать заниматься магазином и дождаться окончания.\n\n"
            "Если не хочешь ждать, нажми [⏩ Пропустить ожидание]."
        )

    if stage == tutorial.STAGE_PREP_WAIT:
        return (
            "Закладчик готовит товар к витрине.\n\n"
            "Можешь дождаться окончания.\n\n"
            "Если не хочешь ждать, нажми [⏩ Пропустить ожидание]."
        )

    if stage == tutorial.STAGE_PRICE:
        return "Нажми [🏷 Витрина]"

    if stage == tutorial.STAGE_SALE_WAIT:
        return (
            "Теперь дождись первой продажи.\n\n"
            "Можешь продолжать играть как обычно.\n\n"
            "Если не хочешь ждать, нажми [⏩ Пропустить ожидание]."
        )

    if stage == tutorial.STAGE_REVIEW:
        order_id = data.get("order_id")
        suffix = f" #{order_id}" if order_id else ""
        return (
            f"Первый заказ{suffix} прошел.\n\n"
            "Выручка еще не равна чистой прибыли. Есть себестоимость товара и выплаты команде.\n\n"
            "После продаж появляются оценки товара и закладчика.\n\n"
            f"Нажми [{CONTINUE_LABEL}], чтобы познакомиться с диспутами."
        )

    if stage == tutorial.STAGE_DISPUTE:
        return "Нажми [📨 Входящие], чтобы открыть первый диспут."

    if stage == tutorial.STAGE_TEAM:
        return (
            "Перед завершением обучения посмотри остальные разделы.\n\n"
            "[👥 Команда]\n"
            "Проверь сотрудников, их нагрузку, депозит и результаты работы.\n\n"
            "[🔎 Нанять]\n"
            "Ищи новых сотрудников и задавай требования к кандидатам.\n\n"
            "[⚙️ Оплата]\n"
            "Настраивай условия выплат для складменов и закладчиков.\n\n"
            "[⚙️ Фасовки]\n"
            "Настраивай, сколько нового товара продавать фасовками по 1, 2 и 5 единиц.\n\n"
            "[📊 Аналитика]\n"
            "Смотри продажи, расходы и прибыль.\n\n"
            "[📨 Входящие]\n"
            "Здесь появляются сообщения и ситуации, которые требуют решения.\n\n"
            "Когда закончишь, нажми [✅ Завершить обучение]."
        )

    return "Обучение завершено."


def _install_continue_button() -> None:
    current = tutorial._append_tutorial_action
    if getattr(current, "_nightshift_copy_update", False):
        return

    def append_tutorial_action(markup: InlineKeyboardMarkup, state: dict) -> InlineKeyboardMarkup:
        result = current(markup, state)
        rows = []
        changed = False
        for row in result.inline_keyboard:
            updated_row = []
            for button in row:
                if button.callback_data == "tutorial:continue" and button.text != CONTINUE_LABEL:
                    button = button.model_copy(update={"text": CONTINUE_LABEL})
                    changed = True
                updated_row.append(button)
            rows.append(updated_row)
        return InlineKeyboardMarkup(inline_keyboard=rows) if changed else result

    append_tutorial_action._nightshift_copy_update = True
    tutorial._append_tutorial_action = append_tutorial_action


def apply_tutorial_copy_update() -> None:
    tutorial._instruction = _instruction
    _install_continue_button()
