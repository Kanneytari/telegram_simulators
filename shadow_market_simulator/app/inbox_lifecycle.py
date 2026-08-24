from __future__ import annotations

from .db import Database




def install_inbox_lifecycle(db: Database) -> None:
    """Install data-level cleanup for notifications that no longer have active candidates."""
    with db.connect() as conn:
        pass
        # Also clean up stale rows left by older application versions.
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
