from pathlib import Path

path = Path(__file__).resolve().parents[1] / "shadow_market_simulator" / "app" / "schema.sql"
text = path.read_text(encoding="utf-8")

candidate_old = """    reliability REAL NOT NULL,\n    attention REAL NOT NULL,\n    honesty REAL NOT NULL,\n    expires_at TEXT NOT NULL,"""
candidate_new = """    reliability REAL NOT NULL,\n    attention REAL NOT NULL,\n    honesty REAL NOT NULL,\n    loyalty REAL NOT NULL,\n    expires_at TEXT NOT NULL,"""
if candidate_old not in text:
    raise SystemExit("candidate schema block not found")
text = text.replace(candidate_old, candidate_new, 1)

client_old = """    fraud_propensity REAL NOT NULL,\n    patience REAL NOT NULL,\n    loyalty REAL NOT NULL,\n    review_tendency REAL NOT NULL"""
client_new = """    fraud_propensity REAL NOT NULL,\n    patience REAL NOT NULL,\n    review_tendency REAL NOT NULL"""
if client_old not in text:
    raise SystemExit("client schema block not found")
text = text.replace(client_old, client_new, 1)

path.write_text(text, encoding="utf-8")
