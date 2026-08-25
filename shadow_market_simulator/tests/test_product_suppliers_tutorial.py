from __future__ import annotations

import asyncio
import random

from app import ui_commerce
from app.core.database import Database
from app.staff.couriers.management import (
    CourierManagementGameService,
    CourierManagementSimulationEngine,
)
from app.tutorial import enable_runtime


class Target:
    def __init__(self):
        self.text = None
        self.reply_markup = None
        self.photo = None

    async def edit_text(self, text, **kwargs):
        self.text = text
        self.reply_markup = kwargs.get("reply_markup")

    async def answer(self, text, **kwargs):
        self.text = text
        self.reply_markup = kwargs.get("reply_markup")


def _labels(target: Target) -> list[str]:
    return [
        button.text
        for row in target.reply_markup.inline_keyboard
        for button in row
    ]


def test_first_purchase_tutorial_enters_suppliers_before_product_category(tmp_path):
    player_id = 94001
    db = Database(str(tmp_path / "suppliers-tutorial.db"))
    db.init()
    enable_runtime(db)

    simulation = CourierManagementSimulationEngine(
        db,
        speed=1.0,
        rng=random.Random(81),
    )
    simulation.seed_catalog()
    assert simulation.ensure_player(player_id, "suppliers-tutorial") is True
    game = CourierManagementGameService(db, simulation, rng=random.Random(82))

    product_root = Target()
    asyncio.run(ui_commerce.render_product_root(product_root, db, game, player_id))
    assert _labels(product_root)[0] == "🤝 Поставщики"
    assert "Нажми [🤝 Поставщики]" in product_root.text

    suppliers = Target()
    asyncio.run(ui_commerce.render_suppliers_root(suppliers, db, game, player_id))
    supplier_labels = _labels(suppliers)
    assert supplier_labels[-2:] == ["Товар", "🏠 Меню"]
    assert "Выбери товар для первой закупки." in suppliers.text
