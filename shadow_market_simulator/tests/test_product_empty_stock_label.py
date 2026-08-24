import random

from app.courier_management import CourierManagementGameService, CourierManagementSimulationEngine
from app.db import Database


PLAYER_ID = 92001


def test_product_button_hides_empty_stock_label(tmp_path):
    from app import ui_commerce
    from app.gameplay_updates import apply_gameplay_updates
    from app.product_ui_update import apply_product_ui_update

    apply_gameplay_updates()
    apply_product_ui_update()

    db = Database(str(tmp_path / "product-empty-stock.db"))
    db.init()
    simulation = CourierManagementSimulationEngine(db, speed=1.0, rng=random.Random(1))
    simulation.seed_catalog()
    simulation.ensure_player(PLAYER_ID, "product-empty-stock")
    game = CourierManagementGameService(db, simulation, rng=random.Random(2))

    products = game.procurement_products(PLAYER_ID)
    markup = ui_commerce._procurement_products_keyboard(db, PLAYER_ID, products)
    product_buttons = markup.inline_keyboard[: len(products)]

    for product, row in zip(products, product_buttons):
        label = row[0].text
        stock_status = ui_commerce._stock_status(db, PLAYER_ID, int(product["id"]))
        assert "нет запаса" not in label.lower()
        if stock_status == "нет запаса":
            assert label == product["title"]
        else:
            assert label == f"{product['title']} · 🚚 {stock_status}"
