from pathlib import Path

path = Path(__file__).resolve().parents[1] / "shadow_market_simulator" / "app" / "analytics_log.py"
text = path.read_text(encoding="utf-8")

text = text.replace(
    "OLD.balance, OLD.rating,",
    "OLD.balance, COALESCE((SELECT trust_score / 20.0 FROM shop_trust_state WHERE player_id=OLD.player_id), NULL),",
)
text = text.replace(
    "(SELECT rating FROM shops WHERE player_id=NEW.player_id)",
    "COALESCE((SELECT trust_score / 20.0 FROM shop_trust_state WHERE player_id=NEW.player_id), NULL)",
)
text = text.replace(
    '"SELECT created_at, balance, rating FROM shops WHERE player_id=?",',
    '''"""SELECT s.created_at, s.balance, st.trust_score\n                   FROM shops s\n                   LEFT JOIN shop_trust_state st ON st.player_id=s.player_id\n                   WHERE s.player_id=?""",''',
)
text = text.replace(
    'float(shop["rating"]) if shop else None,',
    'float(shop["trust_score"]) / 20.0 if shop and shop["trust_score"] is not None else None,',
)

for forbidden in (
    "OLD.rating",
    "SELECT rating FROM shops",
    'shop["rating"]',
):
    if forbidden in text:
        raise SystemExit(f"analytics legacy rating reference remains: {forbidden}")

path.write_text(text, encoding="utf-8")
