import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    metadata   TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages (session_id, id);
CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    system_prompt TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, database_url: str):
        prefix = "sqlite:///"
        if not database_url.startswith(prefix):
            raise ValueError("DATABASE_URL must start with sqlite:///")
        self.path = database_url[len(prefix):]

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def init(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    def ping(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute("SELECT 1 FROM messages LIMIT 1")

    def history(self, session_id: str) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT role, content, metadata FROM messages WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
        messages = []
        for role, content, metadata in rows:
            message = {"role": role, "content": content}
            if metadata:
                message["metadata"] = json.loads(metadata)
            messages.append(message)
        return messages

    def system_prompt(self, session_id: str) -> str | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT system_prompt FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return row[0] if row else None

    def save_turn(
        self,
        session_id: str,
        user_message: str,
        asked_at: str,
        reply: str,
        metadata: dict,
        system_prompt: str | None,
    ) -> None:
        insert = (
            "INSERT INTO messages (session_id, role, content, metadata, created_at) "
            "VALUES (?, ?, ?, ?, ?)"
        )
        with closing(self._connect()) as conn, conn:
            conn.execute(insert, (session_id, "user", user_message, None, asked_at))
            conn.execute(insert, (session_id, "assistant", reply, json.dumps(metadata), now_iso()))
            if system_prompt:
                conn.execute(
                    "INSERT INTO sessions (session_id, system_prompt) VALUES (?, ?) "
                    "ON CONFLICT(session_id) DO UPDATE SET system_prompt = excluded.system_prompt",
                    (session_id, system_prompt),
                )
