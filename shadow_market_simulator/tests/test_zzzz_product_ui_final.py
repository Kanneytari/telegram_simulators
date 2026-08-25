import asyncio
import random

from app.staff.couriers.management import CourierManagementGameService, CourierManagementSimulationEngine
from app.core.database import Database


PLAYER_ID = 93001


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

    async def delete(self):
        return None

    async def answer_photo(self, photo, caption=None, **kwargs):
        self.text = caption
        self.reply_markup = kwargs.get("reply_markup")


def test_final_product_screen_contract(tmp_path):
    from app import ui_commerce
    from app.ui_common import tutorial_hint

    db = Database(str(tmp_path / "product-ui-final.db"))
    db.init()
    simulation = CourierManagementSimulationEngine(db, speed=1.0, rng=random.Random(1))
    simulation.seed_catalog()
    simulation.ensure_player(PLAYER_ID, "product-ui-final")
    game = CourierManagementGameService(db, simulation, rng=random.Random(2))

    products = game.procurement_products(PLAYER_ID)
    markup = ui_commerce._procurement_products_keyboard(db, PLAYER_ID, products)
    labels = [button.text for row in markup.inline_keyboard for button in row]

    product_labels = labels[: len(products)]
    assert all("нет запаса" not in label.lower() for label in product_labels)
    for product, label in zip(products, product_labels):
        stock_status = ui_commerce._stock_status(db, PLAYER_ID, int(product["id"]))
        if stock_status == "нет запаса":
            assert label == product["title"]
        else:
            assert label == f"{product['title']} · 🚚 {stock_status}"

    assert labels[len(products)] == "← Товар"
    assert labels[-1] == "🏠 Меню"
    assert not any(label.startswith("📦 Склад") for label in labels)

    product_root = ui_commerce._product_root_keyboard(
        ui_commerce._warehouse_batch_count(db, PLAYER_ID)
    )
    root_labels = [button.text for row in product_root.inline_keyboard for button in row]
    assert root_labels[0] == "🤝 Поставщики"
    assert root_labels[1].startswith("📦 Склад · ")
    assert root_labels[-1] == "🏠 Меню"
    assert not any(label.startswith("🚚 Склад") for label in root_labels)

    suppliers_target = Target()
    asyncio.run(ui_commerce.render_suppliers_root(suppliers_target, db, game, PLAYER_ID))
    supplier_screen_labels = [
        button.text
        for row in suppliers_target.reply_markup.inline_keyboard
        for button in row
    ]
    assert supplier_screen_labels[: len(products)] == product_labels
    assert supplier_screen_labels[-2:] == ["Товар", "🏠 Меню"]

    target = Target()
    asyncio.run(ui_commerce.render_product_root(target, db, game, PLAYER_ID))
    rendered_root_labels = [
        button.text for row in target.reply_markup.inline_keyboard for button in row
    ]
    assert rendered_root_labels[0] == "🤝 Поставщики"
    assert any(label.startswith("📦 Склад · ") for label in rendered_root_labels)
    assert "<blockquote>Нажми на кнопку [📦 Склад]</blockquote>" in target.text

    assert tutorial_hint("Нажми на кнопку 📦 Товар") == (
        "<blockquote>Нажми на кнопку [📦 Товар]</blockquote>"
    )
    assert tutorial_hint("Проверь и нажми кнопку «✅ Отправить 10 ед.».") == (
        "<blockquote>Проверь и нажми кнопку [✅ Отправить 10 ед.].</blockquote>"
    )
