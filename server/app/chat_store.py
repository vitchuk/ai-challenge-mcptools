"""Персистентное хранилище чата (SQLite): список чатов, история сообщений + память задачи.

Использует ту же БД, что и статьи (`settings.database_path`), но отдельные
таблицы:
- `chats`            — метаданные чата (заголовок = первый вопрос, created/updated);
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

# Длина заголовка чата в БД (клиент дополнительно обрезает при показе).
TITLE_MAX = 120

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    session_id TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chats_updated ON chats (updated_at DESC);

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

# Одноразовый бэкфилл метаданных для чатов, созданных до появления таблицы `chats`.
_BACKFILL = """
INSERT OR IGNORE INTO chats (session_id, title, created_at, updated_at)
SELECT m.session_id,
       COALESCE(NULLIF(SUBSTR(
           (SELECT content FROM chat_messages f
            WHERE f.session_id = m.session_id AND f.role = 'user'
            ORDER BY f.id LIMIT 1), 1, 120), ''), 'Чат'),
       MIN(m.created_at),
       MAX(m.created_at)
FROM chat_messages m
GROUP BY m.session_id
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
        conn.execute(_BACKFILL)  # метаданные чатов, созданных до появления таблицы `chats`


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _make_title(content: str) -> str:
    """Заголовок чата из первого вопроса: нормализуем пробелы и обрезаем."""
    title = " ".join((content or "").split()).strip()
    return title[:TITLE_MAX] if title else "Чат"


def append_message(session_id: str, role: str, content: str) -> None:
    """Добавляет реплику диалога; при первом сообщении создаёт чат и его заголовок."""
    now = _now_iso()
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO chat_messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, now),
        )
        title = _make_title(content) if role == "user" else "Чат"
        conn.execute(
            """
            INSERT INTO chats (session_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET updated_at=excluded.updated_at
            """,
            (session_id, title, now, now),
        )


def list_chats() -> list[dict]:
    """Список чатов с непустой историей, свежие — сверху."""
    with _lock, _connect() as conn:
        rows = conn.execute(
            """
            SELECT c.session_id, c.title, c.created_at, c.updated_at,
                   (SELECT COUNT(*) FROM chat_messages m
                    WHERE m.session_id = c.session_id) AS messages_count
            FROM chats c
            WHERE (SELECT COUNT(*) FROM chat_messages m
                   WHERE m.session_id = c.session_id) > 0
            ORDER BY c.updated_at DESC, c.created_at DESC
            """
        ).fetchall()
    return [
        {
            "session_id": row["session_id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "messages_count": row["messages_count"],
        }
        for row in rows
    ]


def get_chat(session_id: str) -> dict | None:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT session_id, title, created_at, updated_at FROM chats WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "session_id": row["session_id"],
        "title": row["title"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


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


def delete_chat(session_id: str) -> None:
    """Удаляет чат целиком: метаданные, историю сообщений и память задачи."""
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM chats WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM chat_task_states WHERE session_id = ?", (session_id,))
