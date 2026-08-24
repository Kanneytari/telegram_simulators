from __future__ import annotations

from .staff_relationships import StaffRelationshipSimulationEngine


# Fictional balancing values for the game economy. They are not based on
# current real-world illegal-market prices.
EXTRA_PRODUCTS = (
    (4, "MEPHEDRONE", "Мефедрон", 7000, 15.0, 1.00),
    (5, "KETAMINE", "Кетамин", 7500, 9.0, 1.15),
    (6, "LSD", "LSD", 9000, 7.0, 0.85),
)


def _listing_prices(base_price: int) -> dict[int, int]:
    return {
        1: int(round(base_price * 1.05 / 100.0) * 100),
        2: int(round(base_price * 1.95 / 100.0) * 100),
        5: int(round(base_price * 4.55 / 100.0) * 100),
    }


class ExpandedCatalogSimulationEngine(StaffRelationshipSimulationEngine):
    """Live simulation with additional products and backward-compatible listings."""

    def _ensure_extra_listings_conn(self, conn, player_id: int) -> None:
        for product_id, _, _, base_price, _, _ in EXTRA_PRODUCTS:
            for pack_size, price in _listing_prices(base_price).items():
                conn.execute(
                    """INSERT OR IGNORE INTO listings(player_id, product_id, pack_size, price)
                       VALUES (?, ?, ?, ?)""",
                    (player_id, product_id, pack_size, price),
                )

    def seed_catalog(self) -> None:
        super().seed_catalog()
        with self.db.connect() as conn:
            conn.executemany(
                """INSERT OR IGNORE INTO products(
                       id, code, title, base_market_price, base_demand, complaint_modifier
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                EXTRA_PRODUCTS,
            )
            # Keep balancing values deterministic if a previous development build
            # already inserted one of these IDs.
            for product_id, code, title, base_price, demand, modifier in EXTRA_PRODUCTS:
                conn.execute(
                    """UPDATE products
                       SET code=?, title=?, base_market_price=?, base_demand=?,
                           complaint_modifier=?, active=1
                       WHERE id=?""",
                    (code, title, base_price, demand, modifier, product_id),
                )
            player_ids = [int(row[0]) for row in conn.execute("SELECT player_id FROM shops").fetchall()]
            for player_id in player_ids:
                self._ensure_extra_listings_conn(conn, player_id)

    def ensure_player(self, player_id: int, username: str | None) -> bool:
        created = super().ensure_player(player_id, username)
        with self.db.connect() as conn:
            self._ensure_extra_listings_conn(conn, player_id)
        return created
