from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from .db import Database




# The event log deliberately has no foreign key to shops so reset history survives.
ANALYTICS_TRIGGERS = r"""
CREATE TRIGGER IF NOT EXISTS analytics_shop_reset
BEFORE DELETE ON shops
BEGIN
    INSERT INTO analytics_events(
        player_id, run_id, event_kind, event_name, source,
        entity_type, entity_id, balance, rating, time_multiplier, payload_json
    ) VALUES (
        OLD.player_id, OLD.created_at, 'game_event', 'progress_reset', 'system',
        'shop', OLD.player_id, OLD.balance, COALESCE((SELECT trust_score / 20.0 FROM shop_trust_state WHERE player_id=OLD.player_id), NULL),
        COALESCE((SELECT time_multiplier FROM settings WHERE player_id=OLD.player_id), 1.0),
        json_object('total_orders', OLD.total_orders, 'total_revenue', OLD.total_revenue, 'total_profit', OLD.total_profit)
    );
END;

CREATE TRIGGER IF NOT EXISTS analytics_employee_created
AFTER INSERT ON employees
BEGIN
    INSERT INTO analytics_events(player_id, run_id, event_kind, event_name, source, entity_type, entity_id, balance, rating, time_multiplier, payload_json)
    VALUES (
        NEW.player_id, (SELECT created_at FROM shops WHERE player_id=NEW.player_id),
        'game_event', 'employee_added', 'staff', 'employee', NEW.id,
        (SELECT balance FROM shops WHERE player_id=NEW.player_id),
        COALESCE((SELECT trust_score / 20.0 FROM shop_trust_state WHERE player_id=NEW.player_id), NULL),
        COALESCE((SELECT time_multiplier FROM settings WHERE player_id=NEW.player_id), 1.0),
        json_object('role', NEW.role, 'deposit', NEW.deposit)
    );
END;

CREATE TRIGGER IF NOT EXISTS analytics_employee_deactivated
AFTER UPDATE OF active ON employees
WHEN OLD.active = 1 AND NEW.active = 0
BEGIN
    INSERT INTO analytics_events(player_id, run_id, event_kind, event_name, source, entity_type, entity_id, balance, rating, time_multiplier, payload_json)
    VALUES (
        NEW.player_id, (SELECT created_at FROM shops WHERE player_id=NEW.player_id),
        'game_event', 'employee_deactivated', 'staff', 'employee', NEW.id,
        (SELECT balance FROM shops WHERE player_id=NEW.player_id),
        COALESCE((SELECT trust_score / 20.0 FROM shop_trust_state WHERE player_id=NEW.player_id), NULL),
        COALESCE((SELECT time_multiplier FROM settings WHERE player_id=NEW.player_id), 1.0),
        json_object('role', NEW.role, 'deposit_after', NEW.deposit, 'losses', NEW.losses)
    );
END;

CREATE TRIGGER IF NOT EXISTS analytics_supplier_offer_created
AFTER INSERT ON supplier_offers
BEGIN
    INSERT INTO analytics_events(player_id, run_id, event_kind, event_name, source, entity_type, entity_id, balance, rating, time_multiplier, payload_json)
    VALUES (
        NEW.player_id, (SELECT created_at FROM shops WHERE player_id=NEW.player_id),
        'game_event', 'supplier_offer_created', 'procurement', 'supplier_offer', NEW.id,
        (SELECT balance FROM shops WHERE player_id=NEW.player_id),
        COALESCE((SELECT trust_score / 20.0 FROM shop_trust_state WHERE player_id=NEW.player_id), NULL),
        COALESCE((SELECT time_multiplier FROM settings WHERE player_id=NEW.player_id), 1.0),
        json_object('supplier_id', NEW.supplier_id, 'product_id', NEW.product_id, 'quantity', NEW.quantity, 'unit_cost', NEW.unit_cost)
    );
END;

CREATE TRIGGER IF NOT EXISTS analytics_batch_created
AFTER INSERT ON batches
BEGIN
    INSERT INTO analytics_events(player_id, run_id, event_kind, event_name, source, entity_type, entity_id, balance, rating, time_multiplier, payload_json)
    VALUES (
        NEW.player_id, (SELECT created_at FROM shops WHERE player_id=NEW.player_id),
        'game_event', 'batch_created', 'workflow', 'batch', NEW.id,
        (SELECT balance FROM shops WHERE player_id=NEW.player_id),
        COALESCE((SELECT trust_score / 20.0 FROM shop_trust_state WHERE player_id=NEW.player_id), NULL),
        COALESCE((SELECT time_multiplier FROM settings WHERE player_id=NEW.player_id), 1.0),
        json_object('supplier_id', NEW.supplier_id, 'product_id', NEW.product_id, 'quantity', NEW.quantity, 'unit_cost', NEW.unit_cost, 'responsible_employee_id', NEW.responsible_employee_id)
    );
END;

CREATE TRIGGER IF NOT EXISTS analytics_order_created
AFTER INSERT ON orders
BEGIN
    INSERT INTO analytics_events(player_id, run_id, event_kind, event_name, source, entity_type, entity_id, balance, rating, time_multiplier, payload_json)
    VALUES (
        NEW.player_id, (SELECT created_at FROM shops WHERE player_id=NEW.player_id),
        'game_event', 'order_created', 'sales', 'order', NEW.id,
        (SELECT balance FROM shops WHERE player_id=NEW.player_id),
        COALESCE((SELECT trust_score / 20.0 FROM shop_trust_state WHERE player_id=NEW.player_id), NULL),
        COALESCE((SELECT time_multiplier FROM settings WHERE player_id=NEW.player_id), 1.0),
        json_object('client_id', NEW.client_id, 'employee_id', NEW.employee_id, 'batch_id', NEW.batch_id,
                    'product_id', NEW.product_id, 'quantity', NEW.quantity, 'revenue', NEW.revenue,
                    'cost', NEW.cost, 'employee_cost', NEW.employee_cost,
                    'customer_purchase_number', NEW.customer_purchase_number,
                    'customer_was_repeat', NEW.customer_was_repeat)
    );
END;

CREATE TRIGGER IF NOT EXISTS analytics_order_rating_created
AFTER INSERT ON order_ratings
BEGIN
    INSERT INTO analytics_events(player_id, run_id, event_kind, event_name, source, entity_type, entity_id, balance, rating, time_multiplier, payload_json)
    VALUES (
        NEW.player_id, (SELECT created_at FROM shops WHERE player_id=NEW.player_id),
        'game_event', 'order_rated', 'customer', 'order', NEW.order_id,
        (SELECT balance FROM shops WHERE player_id=NEW.player_id),
        COALESCE((SELECT trust_score / 20.0 FROM shop_trust_state WHERE player_id=NEW.player_id), NULL),
        COALESCE((SELECT time_multiplier FROM settings WHERE player_id=NEW.player_id), 1.0),
        json_object('client_id', NEW.client_id, 'product_id', NEW.product_id, 'employee_id', NEW.employee_id,
                    'product_rating', NEW.product_rating, 'courier_rating', NEW.courier_rating)
    );
END;

CREATE TRIGGER IF NOT EXISTS analytics_dispute_opened
AFTER INSERT ON disputes
BEGIN
    INSERT INTO analytics_events(player_id, run_id, event_kind, event_name, source, entity_type, entity_id, balance, rating, time_multiplier, payload_json)
    VALUES (
        NEW.player_id, (SELECT created_at FROM shops WHERE player_id=NEW.player_id),
        'game_event', 'dispute_opened', 'customer', 'dispute', NEW.id,
        (SELECT balance FROM shops WHERE player_id=NEW.player_id),
        COALESCE((SELECT trust_score / 20.0 FROM shop_trust_state WHERE player_id=NEW.player_id), NULL),
        COALESCE((SELECT time_multiplier FROM settings WHERE player_id=NEW.player_id), 1.0),
        json_object('order_id', NEW.order_id, 'true_cause', NEW.true_cause, 'deadline_at', NEW.deadline_at)
    );
END;

CREATE TRIGGER IF NOT EXISTS analytics_dispute_resolved
AFTER UPDATE OF status ON disputes
WHEN OLD.status = 'open' AND NEW.status = 'resolved'
BEGIN
    INSERT INTO analytics_events(player_id, run_id, event_kind, event_name, source, entity_type, entity_id, balance, rating, time_multiplier, payload_json)
    VALUES (
        NEW.player_id, (SELECT created_at FROM shops WHERE player_id=NEW.player_id),
        'game_event', 'dispute_resolved', 'customer', 'dispute', NEW.id,
        (SELECT balance FROM shops WHERE player_id=NEW.player_id),
        COALESCE((SELECT trust_score / 20.0 FROM shop_trust_state WHERE player_id=NEW.player_id), NULL),
        COALESCE((SELECT time_multiplier FROM settings WHERE player_id=NEW.player_id), 1.0),
        json_object('order_id', NEW.order_id, 'decision', NEW.decision, 'refund_amount', NEW.refund_amount,
                    'refund_source', NEW.refund_source, 'refund_employee_id', NEW.refund_employee_id)
    );
END;

CREATE TRIGGER IF NOT EXISTS analytics_inbox_created
AFTER INSERT ON inbox
BEGIN
    INSERT INTO analytics_events(player_id, run_id, event_kind, event_name, source, entity_type, entity_id, balance, rating, time_multiplier, payload_json)
    VALUES (
        NEW.player_id, (SELECT created_at FROM shops WHERE player_id=NEW.player_id),
        'game_event', 'inbox_created', 'inbox', 'inbox', NEW.id,
        (SELECT balance FROM shops WHERE player_id=NEW.player_id),
        COALESCE((SELECT trust_score / 20.0 FROM shop_trust_state WHERE player_id=NEW.player_id), NULL),
        COALESCE((SELECT time_multiplier FROM settings WHERE player_id=NEW.player_id), 1.0),
        json_object('kind', NEW.kind, 'priority', NEW.priority, 'title', NEW.title)
    );
END;

CREATE TRIGGER IF NOT EXISTS analytics_ledger_created
AFTER INSERT ON ledger
BEGIN
    INSERT INTO analytics_events(player_id, run_id, event_kind, event_name, source, entity_type, entity_id, balance, rating, time_multiplier, payload_json)
    VALUES (
        NEW.player_id, (SELECT created_at FROM shops WHERE player_id=NEW.player_id),
        'game_event', 'ledger_entry_created', 'finance', 'ledger', NEW.id,
        (SELECT balance FROM shops WHERE player_id=NEW.player_id),
        COALESCE((SELECT trust_score / 20.0 FROM shop_trust_state WHERE player_id=NEW.player_id), NULL),
        COALESCE((SELECT time_multiplier FROM settings WHERE player_id=NEW.player_id), 1.0),
        json_object('amount', NEW.amount, 'kind', NEW.kind, 'reference_type', NEW.reference_type, 'reference_id', NEW.reference_id)
    );
END;

CREATE TRIGGER IF NOT EXISTS analytics_payroll_created
AFTER INSERT ON payroll_runs
BEGIN
    INSERT INTO analytics_events(player_id, run_id, event_kind, event_name, source, entity_type, entity_id, balance, rating, time_multiplier, payload_json)
    VALUES (
        NEW.player_id, (SELECT created_at FROM shops WHERE player_id=NEW.player_id),
        'game_event', 'payroll_processed', 'finance', 'payroll_run', NEW.id,
        (SELECT balance FROM shops WHERE player_id=NEW.player_id),
        COALESCE((SELECT trust_score / 20.0 FROM shop_trust_state WHERE player_id=NEW.player_id), NULL),
        COALESCE((SELECT time_multiplier FROM settings WHERE player_id=NEW.player_id), 1.0),
        json_object('gross_wages', NEW.gross_wages, 'cash_paid', NEW.cash_paid, 'deposit_added', NEW.deposit_added,
                    'employee_count', NEW.employee_count, 'status', NEW.status)
    );
END;

CREATE TRIGGER IF NOT EXISTS analytics_recruitment_started
AFTER INSERT ON recruitment_campaigns
BEGIN
    INSERT INTO analytics_events(player_id, run_id, event_kind, event_name, source, entity_type, entity_id, balance, rating, time_multiplier, payload_json)
    VALUES (
        NEW.player_id, (SELECT created_at FROM shops WHERE player_id=NEW.player_id),
        'game_event', 'recruitment_campaign_started', 'recruitment', 'recruitment_campaign', NEW.id,
        (SELECT balance FROM shops WHERE player_id=NEW.player_id),
        COALESCE((SELECT trust_score / 20.0 FROM shop_trust_state WHERE player_id=NEW.player_id), NULL),
        COALESCE((SELECT time_multiplier FROM settings WHERE player_id=NEW.player_id), 1.0),
        json_object('channel', NEW.channel, 'role', NEW.role, 'cost', NEW.cost, 'traffic_multiplier', NEW.traffic_multiplier,
                    'duration_hours', NEW.duration_hours, 'min_deposit', NEW.min_deposit,
                    'expected_min', NEW.expected_min, 'expected_max', NEW.expected_max)
    );
END;

CREATE TRIGGER IF NOT EXISTS analytics_recruitment_completed
AFTER UPDATE OF status ON recruitment_campaigns
WHEN OLD.status <> NEW.status AND NEW.status = 'completed'
BEGIN
    INSERT INTO analytics_events(player_id, run_id, event_kind, event_name, source, entity_type, entity_id, balance, rating, time_multiplier, payload_json)
    VALUES (
        NEW.player_id, (SELECT created_at FROM shops WHERE player_id=NEW.player_id),
        'game_event', 'recruitment_campaign_completed', 'recruitment', 'recruitment_campaign', NEW.id,
        (SELECT balance FROM shops WHERE player_id=NEW.player_id),
        COALESCE((SELECT trust_score / 20.0 FROM shop_trust_state WHERE player_id=NEW.player_id), NULL),
        COALESCE((SELECT time_multiplier FROM settings WHERE player_id=NEW.player_id), 1.0),
        json_object('channel', NEW.channel, 'role', NEW.role, 'cost', NEW.cost, 'candidates_created', NEW.candidates_created)
    );
END;

CREATE TRIGGER IF NOT EXISTS analytics_listing_price_changed
AFTER UPDATE OF price ON listings
WHEN OLD.price <> NEW.price
BEGIN
    INSERT INTO analytics_events(player_id, run_id, event_kind, event_name, source, entity_type, entity_id, balance, rating, time_multiplier, payload_json)
    VALUES (
        NEW.player_id, (SELECT created_at FROM shops WHERE player_id=NEW.player_id),
        'game_event', 'listing_price_changed', 'storefront', 'listing', NEW.id,
        (SELECT balance FROM shops WHERE player_id=NEW.player_id),
        COALESCE((SELECT trust_score / 20.0 FROM shop_trust_state WHERE player_id=NEW.player_id), NULL),
        COALESCE((SELECT time_multiplier FROM settings WHERE player_id=NEW.player_id), 1.0),
        json_object('product_id', NEW.product_id, 'pack_size', NEW.pack_size, 'old_price', OLD.price, 'new_price', NEW.price)
    );
END;

CREATE TRIGGER IF NOT EXISTS analytics_speed_changed
AFTER UPDATE OF time_multiplier ON settings
WHEN OLD.time_multiplier <> NEW.time_multiplier
BEGIN
    INSERT INTO analytics_events(player_id, run_id, event_kind, event_name, source, entity_type, entity_id, balance, rating, time_multiplier, payload_json)
    VALUES (
        NEW.player_id, (SELECT created_at FROM shops WHERE player_id=NEW.player_id),
        'game_event', 'time_multiplier_changed', 'admin', 'settings', NEW.player_id,
        (SELECT balance FROM shops WHERE player_id=NEW.player_id),
        COALESCE((SELECT trust_score / 20.0 FROM shop_trust_state WHERE player_id=NEW.player_id), NULL),
        NEW.time_multiplier,
        json_object('old', OLD.time_multiplier, 'new', NEW.time_multiplier)
    );
END;
"""


_NUMERIC_TOKEN = re.compile(r"^-?\d+(?:\.\d+)?$")


def normalize_callback(value: str | None) -> str:
    if not value:
        return "callback.empty"
    parts = value.split(":")
    normalized = ["*" if _NUMERIC_TOKEN.match(part) else part for part in parts]
    return "callback." + ".".join(normalized)


class AnalyticsLogger:
    def __init__(self, db: Database) -> None:
        self.db = db

    def install(self) -> None:
        with self.db.connect() as conn:
            pass
            conn.executescript(ANALYTICS_TRIGGERS)

    def log(
        self,
        player_id: int,
        event_kind: str,
        event_name: str,
        source: str,
        *,
        entity_type: str | None = None,
        entity_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self.db.connect() as conn:
            shop = conn.execute(
                """SELECT s.created_at, s.balance, st.trust_score
                   FROM shops s
                   LEFT JOIN shop_trust_state st ON st.player_id=s.player_id
                   WHERE s.player_id=?""",
                (player_id,),
            ).fetchone()
            settings = conn.execute(
                "SELECT time_multiplier FROM settings WHERE player_id=?",
                (player_id,),
            ).fetchone()
            conn.execute(
                """INSERT INTO analytics_events(
                       player_id, run_id, event_kind, event_name, source,
                       entity_type, entity_id, balance, rating, time_multiplier, payload_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    player_id,
                    shop["created_at"] if shop else None,
                    event_kind,
                    event_name,
                    source,
                    entity_type,
                    entity_id,
                    int(shop["balance"]) if shop else None,
                    float(shop["trust_score"]) / 20.0 if shop and shop["trust_score"] is not None else None,
                    float(settings["time_multiplier"]) if settings else None,
                    json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":")),
                ),
            )

    def log_notification(self, player_id: int, inbox_id: int, kind: str, priority: str) -> None:
        self.log(
            player_id,
            "game_event",
            "notification_sent",
            "telegram",
            entity_type="inbox",
            entity_id=inbox_id,
            payload={"kind": kind, "priority": priority},
        )


class AnalyticsLoggingMiddleware(BaseMiddleware):
    def __init__(self, logger: AnalyticsLogger) -> None:
        self.logger = logger

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        event_name = "unknown"
        if user is not None:
            if isinstance(event, CallbackQuery):
                raw = event.data or ""
                event_name = normalize_callback(raw)
                payload = {
                    "callback_data": raw,
                    "message_id": getattr(event.message, "message_id", None),
                }
            else:
                text = event.text or ""
                if text.startswith("/"):
                    first, *args = text.split(maxsplit=1)
                    command = first.split("@", 1)[0].lower().lstrip("/") or "unknown"
                    event_name = f"command.{command}"
                    payload = {
                        "argument": args[0][:120] if args else None,
                        "message_id": event.message_id,
                    }
                else:
                    event_name = "message.text"
                    payload = {"length": len(text), "message_id": event.message_id}
            try:
                self.logger.log(user.id, "player_action", event_name, "telegram", payload=payload)
            except Exception:
                pass

        try:
            return await handler(event, data)
        except Exception:
            if user is not None:
                try:
                    self.logger.log(
                        user.id,
                        "system",
                        "player_action_handler_error",
                        "telegram",
                        payload={"event": event_name},
                    )
                except Exception:
                    pass
            raise
