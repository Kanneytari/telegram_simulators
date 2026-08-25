import asyncio
import random

from app.courier_management import CourierManagementGameService, CourierManagementSimulationEngine
from app.db import Database


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

    assert any(label.startswith("📦 Склад · ") for label in labels)
    assert not any(label.startswith("🚚 Склад") for label in labels)

    target = Target()
    asyncio.run(ui_commerce.render_product_root(target, db, game, PLAYER_ID))
    assert "<blockquote>Нажми на кнопку [📦 Склад]</blockquote>" in target.text

    assert tutorial_hint("Нажми на кнопку 📦 Товар") == (
        "<blockquote>Нажми на кнопку [📦 Товар]</blockquote>"
    )
    assert tutorial_hint("Проверь и нажми кнопку «✅ Отправить 10 ед.»." ) == (
        "<blockquote>Проверь и нажми кнопку [✅ Отправить 10 ед.].</blockquote>"
    )
