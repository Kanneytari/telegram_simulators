from __future__ import annotations

from . import simulation, tutorial


def _instruction(state: dict) -> str:
    stage = state["stage"]
    data = state["data"]

    if stage == tutorial.STAGE_PROCUREMENT:
        return (
            "Склад пуст. Нажми 📦 Товар и выбери, что купить. "
            "Сравни цену, качество и надёжность поставки. "
            "В дальнейшем любая закупка может оказаться неудачной."
        )
    if stage == tutorial.STAGE_PICKUP_WAIT:
        return (
            "Складмен забирает товар. Обычно это занимает игровое время. "
            "Можешь заниматься другими делами, дождаться окончания или нажать ⏩ Пропустить ожидание."
        )
    if stage == tutorial.STAGE_HANDOFF:
        return (
            "Вернись в меню, нажми 📦 Товар, затем 📦 Склад. "
            "Открой партию и выбери закладчика, которому передашь стафф."
        )
    if stage == tutorial.STAGE_HANDOFF_WAIT:
        return (
            "Складмен передаёт товар закладчику. Можешь продолжать заниматься магазином, "
            "дождаться окончания или нажать ⏩ Пропустить ожидание."
        )
    if stage == tutorial.STAGE_PREP_WAIT:
        return (
            "Закладчик готовит товар к витрине. "
            "Можешь дождаться окончания или нажать ⏩ Пропустить ожидание."
        )
    if stage == tutorial.STAGE_PRICE:
        return (
            "Вернись в меню и нажми 🏷 Витрина. Выбери товар, затем выбери фасовку и измени цену. "
            "Цена влияет на спрос и ожидания покупателей."
        )
    if stage == tutorial.STAGE_SALE_WAIT:
        return (
            "Теперь дождись первой продажи. Можешь продолжать играть как обычно "
            "или нажать ⏩ Пропустить ожидание."
        )
    if stage == tutorial.STAGE_REVIEW:
        order_id = data.get("order_id")
        suffix = f" #{order_id}" if order_id else ""
        return (
            f"Первый заказ{suffix} прошёл. Выручка ещё не равна чистой прибыли. "
            "Есть себестоимость товара и выплаты команде. После продаж появляются оценки товара и закладчика. "
            "Нажми кнопку Продолжить обучение, чтобы познакомиться с диспутами."
        )
    if stage == tutorial.STAGE_DISPUTE:
        return (
            "Открой 📨 Входящие и разбери диспут. Можно запросить пояснение сотрудника, "
            "изучить ситуацию и решить, компенсировать заказ или отказать."
        )
    if stage == tutorial.STAGE_TEAM:
        return (
            "Перед завершением посмотри остальные разделы. "
            "В 👥 Команде можно проверить сотрудников, их нагрузку, депозит и результаты работы. "
            "В Найме можно искать новых сотрудников и задавать требования к кандидатам. "
            "В Оплате можно менять условия выплат для складменов и закладчиков. "
            "В 🏷 Фасовках можно настроить, какая часть нового товара будет продаваться по 1, 2 и 5 единиц. "
            "В 📊 Аналитике можно посмотреть продажи, расходы и прибыль. "
            "В 📨 Входящих появляются сообщения и ситуации, которые требуют твоего решения. "
            "Когда разберёшься, заверши обучение."
        )
    return "Обучение завершено."


def _install_copy_rules() -> None:
    tutorial._instruction = _instruction

    current = simulation.SimulationEngine.ensure_player
    if getattr(current, "_nightshift_tutorial_copy_rules", False):
        return

    def ensure_player(self, player_id: int, username: str | None) -> bool:
        created = current(self, player_id, username)
        if created:
            with self.db.connect() as conn:
                conn.execute(
                    """UPDATE inbox
                       SET body='Склад пуст. Начни с первой закупки в разделе Товар.'
                       WHERE player_id=? AND kind='tutorial'""",
                    (player_id,),
                )
        return created

    ensure_player._nightshift_tutorial_copy_rules = True
    simulation.SimulationEngine.ensure_player = ensure_player


def apply_tutorial_runtime_fixes() -> None:
    """Keep tutorial guidance non-blocking and normalize player-facing copy."""
    _install_copy_rules()
