from __future__ import annotations

from app.presentation.entities import role_html
from app.presentation.vocabulary import ANALYTICS, INBOX, PACKAGING, PAYMENT, PRODUCT, RECRUIT, STOREFRONT, TEAM

from .core import (
    CONTINUE_LABEL,
    STAGE_DISPUTE,
    STAGE_HANDOFF,
    STAGE_HANDOFF_WAIT,
    STAGE_PICKUP_WAIT,
    STAGE_PREP_WAIT,
    STAGE_PRICE,
    STAGE_PROCUREMENT,
    STAGE_REVIEW,
    STAGE_SALE_WAIT,
    STAGE_TEAM,
)


RETURN_TO_MENU = "Вернись в Меню, чтобы продолжить обучение"


def instruction(state: dict) -> str:
    stage = state["stage"]
    data = state["data"]
    if stage == STAGE_PROCUREMENT:
        return (
            "Привет, бро! Рад видеть.\n"
            "Поздравляю, теперь у тебя свой шоп.\n\n"
            "Самое время закупиться первой партией товара.\n"
            f"Нажми [{PRODUCT.label}] и выбери стафф, с которого хочешь начать.\n"
            "Обрати внимание на цену, качество и надежность поставки.\n\n"
            "Мы тут не конфеты продаем. Случиться может что угодно.\n"
            "Смотри в оба.\n"
            "Обнял."
        )
    if stage == STAGE_PICKUP_WAIT:
        return (
            f"{role_html('warehouse', capitalize=True)} забирает товар. Обычно это занимает игровое время.\n\n"
            "Можешь заниматься другими делами и дождаться окончания.\n"
            "Если не хочешь ждать, нажми [⏩ Пропустить ожидание]."
        )
    if stage == STAGE_HANDOFF:
        return f"Нажми [{PRODUCT.label}]"
    if stage == STAGE_HANDOFF_WAIT:
        return (
            f"{role_html('warehouse', capitalize=True)} передает товар {role_html('courier', form='закладчику')}.\n\n"
            "Можешь продолжать заниматься магазином и дождаться окончания.\n"
            "Если не хочешь ждать, нажми [⏩ Пропустить ожидание]."
        )
    if stage == STAGE_PREP_WAIT:
        return (
            f"{role_html('courier', capitalize=True)} готовит товар к витрине.\n\n"
            "Можешь дождаться окончания.\n"
            "Если не хочешь ждать, нажми [⏩ Пропустить ожидание]."
        )
    if stage == STAGE_PRICE:
        return f"Нажми [{STOREFRONT.label}]"
    if stage == STAGE_SALE_WAIT:
        return (
            "Теперь дождись первой продажи.\n\n"
            "Можешь продолжать играть как обычно.\n"
            "Если не хочешь ждать, нажми [⏩ Пропустить ожидание]."
        )
    if stage == STAGE_REVIEW:
        order_id = data.get("order_id")
        suffix = f" #{order_id}" if order_id else ""
        return (
            f"Первый заказ{suffix} прошел.\n\n"
            "Выручка еще не равна чистой прибыли. Есть себестоимость товара и выплаты команде.\n\n"
            f"После продаж появляются оценки товара и {role_html('courier', form='закладчика')}.\n\n"
            f"Нажми [{CONTINUE_LABEL}], чтобы познакомиться с диспутами."
        )
    if stage == STAGE_DISPUTE:
        return f"Нажми [{INBOX.label}], чтобы открыть первый диспут."
    if stage == STAGE_TEAM:
        return (
            "Перед завершением обучения посмотри остальные разделы.\n\n"
            f"[{TEAM.label}]\n"
            "Проверь сотрудников, их нагрузку, депозит и результаты работы.\n\n"
            f"[{RECRUIT.label}]\n"
            "Ищи новых сотрудников и задавай требования к кандидатам.\n\n"
            f"[{PAYMENT.label}]\n"
            f"Настраивай условия выплат для {role_html('warehouse', form='складменов')} и {role_html('courier', form='закладчиков')}.\n\n"
            f"[{PACKAGING.label}]\n"
            "Настраивай, сколько нового товара продавать фасовками по 1, 2 и 5 единиц.\n\n"
            f"[{ANALYTICS.label}]\n"
            "Смотри продажи, расходы и прибыль.\n\n"
            f"[{INBOX.label}]\n"
            "Здесь появляются сообщения и ситуации, которые требуют решения.\n\n"
            "Когда закончишь, нажми [✅ Завершить обучение]."
        )
    return "Обучение завершено."
