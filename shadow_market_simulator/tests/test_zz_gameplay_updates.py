import asyncio
import random
from datetime import timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.courier_management import CourierManagementGameService, CourierManagementSimulationEngine
from app.db import Database
from app.simulation import iso, utcnow


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
    from app.gameplay_updates import apply_gameplay_updates
    from app.handoff_copy_update import apply_handoff_copy_update

    apply_gameplay_updates()
    apply_handoff_copy_update()
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
    from app import staff_relationships

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
    assert all(int(row["total"]) == 5 for row in product_rows)


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
    from app.ui_common import _normalize_menu_buttons

    db, _, game = make_system(tmp_path, seed=307)
    products = game.procurement_products(PLAYER_ID)
    procurement = ui_commerce._procurement_products_keyboard(db, PLAYER_ID, products)
    procurement_labels = _labels(procurement)

    product_labels = procurement_labels[: len(EXPECTED_PRODUCTS)]
    assert all("предлож" not in label.lower() for label in product_labels)
    assert all(" · 🚚 " in label for label in product_labels)
    assert procurement_labels[-1] == "🏠 Меню"

    storefront = ui_commerce._sales_root_keyboard([])
    assert _labels(storefront) == ["⚙️ Фасовки", "🏠 Меню"]

    raw = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="Меню", callback_data="menu:home")
        ]]
    )
    normalized = _normalize_menu_buttons(raw)
    assert _labels(normalized) == ["🏠 Меню"]


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


def test_handoff_copy_icons_and_master_stash_status(tmp_path):
    from app import ui_staff_handlers, workflow

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
    assert f"Складмен: 🚚 {warehouse['alias']}" in target.text
    assert "готова к передаче" not in target.text
    assert "Выберите кладмена" in target.text

    labels = _labels(target.reply_markup)
    courier_buttons = [label for label in labels if retail["alias"] in label]
    assert courier_buttons and all(label.startswith("👤 ") for label in courier_buttons)
    assert "🏠 Меню" in labels
