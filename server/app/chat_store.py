"""Персистентное хранилище чата (SQLite): история сообщений + память задачи.

Использует ту же БД, что и статьи (`settings.database_path`), но отдельные
таблицы:
- `chat_messages`    — реплики диалога по сессии (роль, текст, время);
- `chat_task_states` — память задачи сессии (цель, уточнения, ограничения) в JSON.

Модуль не импортирует chat/rag/tools — только config, чтобы не было циклов.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from .config import get_settings

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages (session_id, id);

CREATE TABLE IF NOT EXISTS chat_task_states (
    session_id TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _db_path() -> Path:
    path = get_settings().database_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_tables() -> None:
    with _lock, _connect() as conn:
        conn.executescript(SCHEMA)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append_message(session_id: str, role: str, content: str) -> None:
    """Добавляет реплику диалога в историю сессии."""
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO chat_messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, _now_iso()),
        )


def load_history(session_id: str, limit: int | None = None) -> list[dict]:
    """Возвращает историю диалога в хронологическом порядке.

    limit — сколько последних реплик вернуть (None — все).
    """
    query = "SELECT role, content FROM chat_messages WHERE session_id = ?"
    params: list = [session_id]
    if limit is not None and limit > 0:
        query += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        rows = None
        with _lock, _connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]
    query += " ORDER BY id"
    with _lock, _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in rows]


def count_messages(session_id: str) -> int:
    with _lock, _connect() as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM chat_messages WHERE session_id = ?", (session_id,)
            ).fetchone()[0]
        )


def save_task_state(session_id: str, state: dict) -> None:
    """Сохраняет память задачи сессии (перезаписывает)."""
    payload = json.dumps(state or {}, ensure_ascii=False)
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO chat_task_states (session_id, state_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                state_json=excluded.state_json,
                updated_at=excluded.updated_at
            """,
            (session_id, payload, _now_iso()),
        )


def load_task_state(session_id: str) -> dict | None:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT state_json FROM chat_task_states WHERE session_id = ?", (session_id,)
        ).fetchone()
    if row is None:
        return None
    try:
        parsed = json.loads(row["state_json"])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def clear_session(session_id: str) -> None:
    """Удаляет историю и память задачи сессии."""
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM chat_task_states WHERE session_id = ?", (session_id,))
