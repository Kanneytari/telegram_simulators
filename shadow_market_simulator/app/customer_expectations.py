from __future__ import annotations

from .procurement_market import ProcurementMarketSimulationEngine
from .simulation import clamp


class PriceExpectationSimulationEngine(ProcurementMarketSimulationEngine):
    """Makes customer review expectations depend on price paid versus the product market baseline."""

    @staticmethod
    def price_quality_adjustment(price_ratio: float) -> float:
        """Translate price positioning into perceived-quality points.

        Discounts give a modest value-for-money bonus; markups increase expectations more
        aggressively. The effect is intentionally capped so price cannot fully hide very bad
        quality or automatically destroy genuinely excellent batches.
        """
        ratio = max(0.1, float(price_ratio))
        if ratio < 1.0:
            return min(10.0, (1.0 - ratio) * 35.0)
        return -min(18.0, (ratio - 1.0) * 50.0)

    @classmethod
    def perceived_quality(cls, quality: float, price_ratio: float) -> float:
        return clamp(float(quality) + cls.price_quality_adjustment(price_ratio), 35.0, 99.0)

    def _create_review(self, conn, player_id: int, order_id: int, *, force: bool) -> int | None:
        exists = conn.execute("SELECT id FROM reviews WHERE order_id=?", (order_id,)).fetchone()
        if exists:
            return int(exists["id"])

        row = conn.execute(
            """SELECT o.*, c.review_tendency, e.attention, e.stress,
                      p.title product_title, p.base_market_price,
                      d.true_cause, d.decision
               FROM orders o
               JOIN clients c ON c.id=o.client_id
               JOIN employees e ON e.id=o.employee_id
               JOIN products p ON p.id=o.product_id
               LEFT JOIN disputes d ON d.order_id=o.id
               WHERE o.id=? AND o.player_id=?""",
            (order_id, player_id),
        ).fetchone()
        if not row:
            return None

        probability = clamp(0.35 + float(row["review_tendency"]) * 0.55, 0.35, 0.90)
        if not force and self.rng.random() > probability:
            return None

        quality = float(row["quality"])
        quantity = max(1, int(row["quantity"]))
        paid_unit_price = float(row["revenue"]) / quantity
        market_unit_price = max(1.0, float(row["base_market_price"]))
        price_ratio = paid_unit_price / market_unit_price
        adjustment = self.price_quality_adjustment(price_ratio)
        perceived = self.perceived_quality(quality, price_ratio)

        if perceived >= 90:
            stars = 5
            quality_sentiment = "good"
            quality_text = self.rng.choice([
                "Качество отличное, к товару вопросов нет.",
                "По качеству всё стабильно, покупкой доволен.",
            ])
        elif perceived >= 80:
            stars = 4
            quality_sentiment = "good"
            quality_text = self.rng.choice([
                "Качество хорошее, всё устроило.",
                "По товару всё нормально, без серьёзных замечаний.",
            ])
        elif perceived >= 68:
            stars = 3
            quality_sentiment = "neutral"
            quality_text = self.rng.choice([
                "Качество среднее, ожидал немного лучше.",
                "По качеству есть вопросы, но в целом нормально.",
            ])
        else:
            stars = 2
            quality_sentiment = "bad"
            quality_text = self.rng.choice([
                "Качество заметно хуже ожиданий.",
                "Товар разочаровал по качеству.",
            ])

        if price_ratio <= 0.90 and adjustment >= 3.0:
            value_text = self.rng.choice([
                "За эту цену результат выглядит достойно.",
                "С учётом цены впечатление скорее положительное.",
            ])
        elif price_ratio >= 1.10 and adjustment <= -5.0:
            value_text = self.rng.choice([
                "За такую цену ожидал более высокого качества.",
                "При такой цене требования к качеству выше.",
            ])
        else:
            value_text = ""

        delivery_score = float(row["attention"]) - max(0.0, float(row["stress"]) - 55.0) / 180.0
        cause = row["true_cause"]
        if cause in {"EMPLOYEE_ERROR", "DESCRIPTION_ERROR"}:
            delivery_score = min(delivery_score, 0.45)
        if cause == "QUALITY_COMPLAINT":
            quality_sentiment = "bad"
            stars = min(stars, 2)
            quality_text = "По качеству этой покупки остались серьёзные вопросы."

        if delivery_score >= 0.87:
            delivery_sentiment = "good"
            delivery_text = self.rng.choice([
                "По доставке всё без вопросов.",
                "Сотрудник отработал аккуратно.",
            ])
        elif delivery_score >= 0.68:
            delivery_sentiment = "neutral"
            delivery_text = "По доставке нормально, но можно аккуратнее."
        else:
            delivery_sentiment = "bad"
            stars = max(1, stars - 1)
            delivery_text = self.rng.choice([
                "По доставке был косяк, описание подвело.",
                "Сотрудник допустил ошибку, пришлось разбираться.",
            ])

        if row["decision"] in {"refund", "partial", "auto_partial"} and force:
            stars = min(5, stars + 1)
            service_text = "Поддержка магазина ситуацию в итоге решила."
        elif row["decision"] == "reject" and force:
            stars = max(1, stars - 1)
            service_text = "По решению магазина остался недоволен."
        else:
            service_text = ""

        text = " ".join(
            part for part in (quality_text, value_text, delivery_text, service_text) if part
        )
        cur = conn.execute(
            """INSERT INTO reviews(
                   player_id, order_id, client_id, product_id, employee_id,
                   rating, text, quality_sentiment, delivery_sentiment
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                player_id,
                order_id,
                row["client_id"],
                row["product_id"],
                row["employee_id"],
                stars,
                text,
                quality_sentiment,
                delivery_sentiment,
            ),
        )
        conn.execute(
            "UPDATE shops SET rating=MAX(1.0, MIN(5.0, rating*0.985 + ?*0.015)) WHERE player_id=?",
            (stars, player_id),
        )
        return int(cur.lastrowid)
