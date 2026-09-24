"""Работа с SQLite: схема, upsert статей, обрезка до Y записей, чтение."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import get_settings

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    story_id       INTEGER PRIMARY KEY,
    title          TEXT NOT NULL,
    url            TEXT NOT NULL,
    author         TEXT,
    theme          TEXT,
    tags           TEXT,
    rating         INTEGER,
    comments_count INTEGER,
    body_text      TEXT,
    images         TEXT,
    videos         TEXT,
    published_at   TEXT,
    parsed_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_articles_story_id ON articles (story_id DESC);
"""


def _db_path() -> Path:
    path = get_settings().database_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with _lock, _connect() as conn:
        conn.executescript(SCHEMA)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dump_json(value: Any) -> str:
    return json.dumps(value or [], ensure_ascii=False)


def _load_json(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def upsert_articles(articles: Iterable[dict]) -> int:
    """Сохраняет статьи, обновляя существующие по story_id. Возвращает кол-во записанных."""
    rows = list(articles)
    if not rows:
        return 0
    parsed_at = _now_iso()
    with _lock, _connect() as conn:
        conn.executemany(
            """
            INSERT INTO articles (
                story_id, title, url, author, theme, tags, rating,
                comments_count, body_text, images, videos, published_at, parsed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(story_id) DO UPDATE SET
                title=excluded.title,
                url=excluded.url,
                author=excluded.author,
                theme=excluded.theme,
                tags=excluded.tags,
                rating=excluded.rating,
                comments_count=excluded.comments_count,
                body_text=excluded.body_text,
                images=excluded.images,
                videos=excluded.videos,
                published_at=excluded.published_at,
                parsed_at=excluded.parsed_at
            """,
            [
                (
                    int(row["story_id"]),
                    row.get("title") or "",
                    row.get("url") or "",
                    row.get("author"),
                    row.get("theme"),
                    _dump_json(row.get("tags")),
                    row.get("rating"),
                    row.get("comments_count"),
                    row.get("body_text"),
                    _dump_json(row.get("images")),
                    _dump_json(row.get("videos")),
                    row.get("published_at"),
                    parsed_at,
                )
                for row in rows
            ],
        )
    return len(rows)


def trim_to_max() -> int:
    """Оставляет только Y последних статей (по убыванию story_id)."""
    max_articles = get_settings().max_articles
    with _lock, _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        if total <= max_articles:
            return 0
        cursor = conn.execute(
            """
            DELETE FROM articles
            WHERE story_id NOT IN (
                SELECT story_id FROM articles ORDER BY story_id DESC LIMIT ?
            )
            """,
            (max_articles,),
        )
        return cursor.rowcount


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "story_id": row["story_id"],
        "title": row["title"],
        "url": row["url"],
        "author": row["author"],
        "theme": row["theme"],
        "tags": _load_json(row["tags"]),
        "rating": row["rating"],
        "comments_count": row["comments_count"],
        "body_text": row["body_text"],
        "images": _load_json(row["images"]),
        "videos": _load_json(row["videos"]),
        "published_at": row["published_at"],
        "parsed_at": row["parsed_at"],
    }


def get_articles(limit: int = 50) -> list[dict]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM articles ORDER BY story_id DESC LIMIT ?", (int(limit),)
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_articles_for_summary(count: int) -> list[dict]:
    """Последние N статей — для тула саммаризации."""
    return get_articles(limit=count)


def count_articles() -> int:
    with _lock, _connect() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0])


def last_parsed_at() -> str | None:
    with _lock, _connect() as conn:
        row = conn.execute("SELECT MAX(parsed_at) FROM articles").fetchone()
    return row[0] if row and row[0] else None
