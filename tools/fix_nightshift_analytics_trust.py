import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
app = root / "shadow_market_simulator" / "app"

analytics_path = app / "analytics_log.py"
text = analytics_path.read_text(encoding="utf-8")
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
for forbidden in ("OLD.rating", "SELECT rating FROM shops", 'shop["rating"]'):
    if forbidden in text:
        raise SystemExit(f"analytics legacy rating reference remains: {forbidden}")
analytics_path.write_text(text, encoding="utf-8")

schema_path = app / "schema.sql"
schema = schema_path.read_text(encoding="utf-8")
schema, removed = re.subn(
    r"CREATE TRIGGER analytics_[\s\S]*?END;\n\n",
    "",
    schema,
)
if removed == 0 and "CREATE TRIGGER analytics_" in schema:
    raise SystemExit("failed to remove duplicated analytics triggers from schema")
if "SELECT rating FROM shops" in schema or "OLD.rating" in schema:
    raise SystemExit("legacy shop rating reference remains in schema")
schema_path.write_text(schema, encoding="utf-8")
