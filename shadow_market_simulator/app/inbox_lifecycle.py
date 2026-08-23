from __future__ import annotations

from .db import Database


INBOX_LIFECYCLE_SCHEMA = """
CREATE TRIGGER IF NOT EXISTS trg_close_empty_recruitment_result_on_insert
AFTER INSERT ON inbox
WHEN NEW.kind='recruitment_result'
BEGIN
    UPDATE inbox
       SET status='closed'
     WHERE id=NEW.id
       AND NOT EXISTS (
           SELECT 1
             FROM candidates c
            WHERE c.player_id=NEW.player_id
              AND c.status='open'
              AND c.campaign_id IS NOT NULL
       );
END;

CREATE TRIGGER IF NOT EXISTS trg_close_recruitment_result_after_candidate_update
AFTER UPDATE OF status ON candidates
WHEN OLD.status='open' AND NEW.status<>'open'
BEGIN
    UPDATE inbox
       SET status='closed'
     WHERE player_id=NEW.player_id
       AND kind='recruitment_result'
       AND status='open'
       AND NOT EXISTS (
           SELECT 1
             FROM candidates c
            WHERE c.player_id=NEW.player_id
              AND c.status='open'
              AND c.campaign_id IS NOT NULL
       );
END;

CREATE TRIGGER IF NOT EXISTS trg_close_recruitment_result_after_candidate_delete
AFTER DELETE ON candidates
WHEN OLD.status='open'
BEGIN
    UPDATE inbox
       SET status='closed'
     WHERE player_id=OLD.player_id
       AND kind='recruitment_result'
       AND status='open'
       AND NOT EXISTS (
           SELECT 1
             FROM candidates c
            WHERE c.player_id=OLD.player_id
              AND c.status='open'
              AND c.campaign_id IS NOT NULL
       );
END;
"""


def install_inbox_lifecycle(db: Database) -> None:
    """Install data-level cleanup for notifications that no longer have active candidates."""
    with db.connect() as conn:
        conn.executescript(INBOX_LIFECYCLE_SCHEMA)
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
