from __future__ import annotations

from ..core.database import Database


def install_inbox_lifecycle(db: Database) -> None:
    """Close recruitment notifications that no longer have active candidates."""
    with db.connect() as conn:
        conn.execute(
            """UPDATE inbox
               SET status='closed'
               WHERE kind='recruitment_result' AND status='open'
                 AND NOT EXISTS (
                     SELECT 1 FROM candidates c
                     WHERE c.player_id=inbox.player_id
                       AND c.status='open'
                       AND c.campaign_id IS NOT NULL
                 )"""
        )
