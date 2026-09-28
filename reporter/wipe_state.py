"""Durable record of wipe reaction alerts already sent to administrators."""

import json
import sqlite3
from pathlib import Path


class AlertStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS active_alerts (
                guild_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                choices TEXT NOT NULL,
                alerted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, message_id, user_id)
            )
            """
        )
        self._db.commit()

    def active_users(self, guild_id: int, message_id: int) -> set[int]:
        rows = self._db.execute(
            "SELECT user_id FROM active_alerts WHERE guild_id = ? AND message_id = ?",
            (guild_id, message_id),
        )
        return {user_id for (user_id,) in rows}

    def mark_sent(
        self, guild_id: int, message_id: int, user_id: int, choices: frozenset[str]
    ) -> None:
        self._db.execute(
            """
            INSERT OR IGNORE INTO active_alerts
                (guild_id, message_id, user_id, choices)
            VALUES (?, ?, ?, ?)
            """,
            (guild_id, message_id, user_id, json.dumps(sorted(choices))),
        )
        self._db.commit()

    def clear_except(
        self, guild_id: int, message_id: int, active_user_ids: set[int]
    ) -> None:
        stale_ids = self.active_users(guild_id, message_id) - active_user_ids
        self._db.executemany(
            """
            DELETE FROM active_alerts
            WHERE guild_id = ? AND message_id = ? AND user_id = ?
            """,
            [(guild_id, message_id, user_id) for user_id in stale_ids],
        )
        self._db.commit()

    def clear_message(self, guild_id: int, message_id: int) -> None:
        self._db.execute(
            "DELETE FROM active_alerts WHERE guild_id = ? AND message_id = ?",
            (guild_id, message_id),
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()
