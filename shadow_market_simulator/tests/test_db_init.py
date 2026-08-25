from app.core.database import Database


def test_database_init_can_run_twice_without_losing_data(tmp_path):
    db = Database(str(tmp_path / "repeat.db"))
    db.init()
    with db.connect() as conn:
        conn.execute("INSERT INTO shops(player_id, username) VALUES (?, ?)", (42, "repeat"))

    db.init()

    with db.connect() as conn:
        shop = conn.execute("SELECT username FROM shops WHERE player_id=42").fetchone()
        analytics_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='analytics_events'"
        ).fetchone()
    assert shop["username"] == "repeat"
    assert analytics_table is not None
