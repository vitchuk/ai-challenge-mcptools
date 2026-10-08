"""Кольцевой буфер LLM-вызовов в памяти для вкладки LOG.

Хранит последние MAX_ENTRIES вызовов (контекст запроса и ответ). Не персистится:
после рестарта сервера лог пуст.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone

MAX_ENTRIES = 200

_lock = threading.Lock()
_entries: deque[dict] = deque(maxlen=MAX_ENTRIES)
_counter = 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_call(
    *,
    phase: str,
    provider: str,
    model: str,
    messages: list[dict],
    response: dict | None = None,
    tools_count: int = 0,
    duration_ms: float | None = None,
    error: str | None = None,
) -> dict:
    """Сохраняет один вызов LLM. phase: chat / rag / aux."""
    global _counter
    with _lock:
        _counter += 1
        entry = {
            "id": _counter,
            "ts": _now_iso(),
            "phase": phase,
            "provider": provider,
            "model": model,
            "messages": messages,
            "tools_count": tools_count,
            "response": response,
            "duration_ms": duration_ms,
            "error": error,
        }
        _entries.append(entry)
        return entry


def recent(limit: int = 50) -> list[dict]:
    """Последние вызовы (свежие сверху)."""
    with _lock:
        items = list(_entries)
    items.reverse()
    return items[: max(1, limit)]


def clear() -> int:
    """Очищает лог, возвращает число удалённых записей."""
    with _lock:
        count = len(_entries)
        _entries.clear()
    return count
