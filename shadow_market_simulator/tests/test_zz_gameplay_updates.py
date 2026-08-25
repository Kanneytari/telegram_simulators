import asyncio
import random
from datetime import timedelta

from app.staff.couriers.management import CourierManagementGameService, CourierManagementSimulationEngine
from app.core.database import Database
from app.engine.simulation import iso, utcnow


PLAYER_ID = 91001
EXPECTED_PRODUCTS = [
    "Amphetamine",
    "MDMA",
    "Cocaine",
    "Mephedrone",
    "LSD",
    "Hash",
    "Weed",
]
EXPECTED_BATCH_SIZES = {50, 100, 250, 500, 1000}


def make_system(tmp_path, seed=101):
    
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = CourierManagementSimulationEngine(db, speed=1.0, rng=random.Random(seed))
    simulation.seed_catalog()
    simulation.ensure_player(PLAYER_ID, "verification")
    game = CourierManagementGameService(db, simulation, rng=random.Random(seed + 1))
    return db, simulation, game


def _labels(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


def test_updated_catalog_market_and_sales_pacing(tmp_path):
    import app.staff.relationships as staff_relationships

    db, _, game = make_system(tmp_path)

    with db.connect() as conn:
        products = conn.execute(
            "SELECT id, code, title FROM products WHERE active=1 ORDER BY id"
        ).fetchall()
        ketamine = conn.execute(
            "SELECT active FROM products WHERE code='KETAMINE'"
        ).fetchone()
        offers = conn.execute(
            """SELECT product_id, COUNT(*) count
               FROM supplier_offers
               WHERE player_id=? AND status='open'
               GROUP BY product_id ORDER BY product_id""",
            (PLAYER_ID,),
        ).fetchall()
        quantities = {
            int(row[0])
            for row in conn.execute(
                "SELECT DISTINCT quantity FROM supplier_offers WHERE player_id=? AND status='open'",
                (PLAYER_ID,),
            ).fetchall()
        }
        listings = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE player_id=?",
            (PLAYER_ID,),
        ).fetchone()[0]

    assert [row["title"] for row in products] == EXPECTED_PRODUCTS
    assert ketamine is None or int(ketamine["active"]) == 0
    assert len(offers) == len(EXPECTED_PRODUCTS)
    assert all(int(row["count"]) == 5 for row in offers)
    assert quantities <= EXPECTED_BATCH_SIZES
    assert quantities
    assert int(listings) == len(EXPECTED_PRODUCTS) * 3
    assert staff_relationships.SALES_ACTIVITY_MULTIPLIER == 4.0

    product_rows = game.procurement_products(PLAYER_ID)
    assert len(product_rows) == len(EXPECTED_PRODUCTS)
    assert all(
        int(row["total"]) == len(game.offers(PLAYER_ID, int(row["id"])))
        for row in product_rows
    )


def test_market_rotates_one_or_two_offers_every_fifteen_minutes(tmp_path):
    db, simulation, _ = make_system(tmp_path, seed=211)

    with db.connect() as conn:
        before = {
            int(row[0])
            for row in conn.execute(
                "SELECT id FROM supplier_offers WHERE player_id=? AND status='open'",
                (PLAYER_ID,),
            ).fetchall()
        }
        conn.execute(
            "UPDATE procurement_market_state SET last_rotation_at=? WHERE player_id=?",
            (iso(utcnow() - timedelta(minutes=16)), PLAYER_ID),
        )

    simulation.refresh_procurement_market(PLAYER_ID)

    with db.connect() as conn:
        after = {
            int(row[0])
            for row in conn.execute(
                "SELECT id FROM supplier_offers WHERE player_id=? AND status='open'",
                (PLAYER_ID,),
            ).fetchall()
        }
        counts = conn.execute(
            """SELECT product_id, COUNT(*) count
               FROM supplier_offers
               WHERE player_id=? AND status='open'
               GROUP BY product_id""",
            (PLAYER_ID,),
        ).fetchall()

    removed = before - after
    added = after - before
    assert 1 <= len(removed) <= 2
    assert len(added) == len(removed)
    assert all(int(row["count"]) == 5 for row in counts)


def test_procurement_storefront_and_global_menu_labels(tmp_path):
    from app import ui_commerce
    from app.presentation.vocabulary import HOME, button

    db, _, game = make_system(tmp_path, seed=307)
    products = game.procurement_products(PLAYER_ID)
    procurement = ui_commerce._procurement_products_keyboard(db, PLAYER_ID, products)
    procurement_labels = _labels(procurement)

    product_labels = procurement_labels[: len(EXPECTED_PRODUCTS)]
    assert all("предлож" not in label.lower() for label in product_labels)
    assert all("нет запаса" not in label.lower() for label in product_labels)
    for product, label in zip(products, product_labels):
        warehouse_units = ui_commerce._warehouse_stock_units(db, PLAYER_ID, int(product["id"]))
        assert label == f"{product['title']} · 🚚 {warehouse_units} ед."
    assert procurement_labels[len(EXPECTED_PRODUCTS)] == "📦 Товар"
    assert procurement_labels[-1] == "🏠 Меню"
    assert not any(label.startswith("📦 Склад") for label in procurement_labels)

    product_root = ui_commerce._product_root_keyboard(
        ui_commerce._warehouse_batch_count(db, PLAYER_ID)
    )
    product_root_labels = _labels(product_root)
    assert product_root_labels[0] == "🤝 Поставщики"
    assert product_root_labels[1].startswith("📦 Склад · ")
    assert product_root_labels[-1] == "🏠 Меню"
    assert not any(label.startswith("🚚 Склад") for label in product_root_labels)

    storefront = ui_commerce._sales_root_keyboard([])
    assert _labels(storefront) == ["⚙️ Фасовки", "🏠 Меню"]

    assert button(HOME).text == "🏠 Меню"


def test_tutorial_button_mentions_use_square_brackets():
    from app.ui_common import tutorial_hint

    assert tutorial_hint("Нажми на кнопку 📦 Товар") == (
        "<blockquote>Нажми на кнопку [📦 Товар]</blockquote>"
    )
    assert tutorial_hint("Нажми на кнопку 📦 Склад") == (
        "<blockquote>Нажми на кнопку [📦 Склад]</blockquote>"
    )
    assert tutorial_hint("Проверь и нажми кнопку «✅ Отправить 10 ед.».") == (
        "<blockquote>Проверь и нажми кнопку [✅ Отправить 10 ед.].</blockquote>"
    )


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


def test_product_screen_uses_package_warehouse_button_and_tutorial(tmp_path):
    from app import ui_commerce

    db, _, game = make_system(tmp_path, seed=353)
    target = Target()
    asyncio.run(ui_commerce.render_product_root(target, db, game, PLAYER_ID))

    assert "<blockquote>Нажми на кнопку [📦 Склад]</blockquote>" in target.text
    labels = _labels(target.reply_markup)
    assert any(label.startswith("📦 Склад · ") for label in labels)
    assert not any(label.startswith("🚚 Склад") for label in labels)
    assert not any("нет запаса" in label.lower() for label in labels)


def test_handoff_copy_icons_and_master_stash_status(tmp_path):
    from app import ui_staff_handlers
    import app.commerce.workflow as workflow

    db, _, game = make_system(tmp_path, seed=401)
    with db.connect() as conn:
        batch = conn.execute(
            """SELECT b.id, b.remaining
               FROM batches b JOIN employees e ON e.id=b.responsible_employee_id
               WHERE b.player_id=? AND b.status='warehouse' AND b.remaining>=10
                 AND e.role='warehouse'
               ORDER BY b.id LIMIT 1""",
            (PLAYER_ID,),
        ).fetchone()
        warehouse = conn.execute(
            "SELECT id, alias FROM employees WHERE player_id=? AND role='warehouse' AND active=1 LIMIT 1",
            (PLAYER_ID,),
        ).fetchone()
        retail = conn.execute(
            "SELECT id, alias FROM employees WHERE player_id=? AND role='courier' AND active=1 ORDER BY id LIMIT 1",
            (PLAYER_ID,),
        ).fetchone()

    assert batch and warehouse and retail
    result = game.allocate_to_retail(
        PLAYER_ID,
        int(batch["id"]),
        int(retail["id"]),
        10,
    )

    assert result.startswith("<b>✅ Принято</b>")
    assert f"🚚 {warehouse['alias']} готовит мастер-клад" in result
    assert f"👤 {retail['alias']}" in result
    assert "готовит передачу" not in result
    assert workflow.TASK_LABELS["handoff"] == "готовит мастер-клад"

    statuses = {
        int(row["id"]): str(row["status_text"])
        for row in game.employees(PLAYER_ID)
    }
    assert "готовит мастер-клад" in statuses[int(warehouse["id"])]

    target = Target()
    asyncio.run(
        ui_staff_handlers.render_batch(
            target,
            game,
            PLAYER_ID,
            int(batch["id"]),
            flash=result,
        )
    )
    assert target.text.startswith("<b>✅ Принято</b>")
    assert f"🚚 <b>Складмен</b>: 🚚 <b>{warehouse['alias']}</b>" in target.text
    assert "готова к передаче" not in target.text
    assert "Выберите 👤 <b>кладмена</b>" in target.text

    labels = _labels(target.reply_markup)
    courier_buttons = [label for label in labels if retail["alias"] in label]
    assert courier_buttons and all(label.startswith("👤 ") for label in courier_buttons)
    assert "🏠 Меню" in labels
