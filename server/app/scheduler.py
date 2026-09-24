"""Планировщик периодического парсинга pikabu.ru/best."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from . import db, parser
from .config import get_settings

logger = logging.getLogger(__name__)

JOB_ID = "pikabu_best_parse"

_scheduler: AsyncIOScheduler | None = None
_parse_lock = asyncio.Lock()
_state: dict = {
    "running": False,
    "last_run_at": None,
    "last_error": None,
    "last_parsed_count": None,
    "total_runs": 0,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone=timezone.utc)
    return _scheduler


async def parse_now() -> dict:
    """Один прогон парсинга /best с записью в БД. Возвращает статистику."""
    async with _parse_lock:
        settings = get_settings()
        try:
            articles = await parser.fetch_best(limit=settings.posts_per_fetch)
            saved = db.upsert_articles(articles)
            trimmed = db.trim_to_max()
            _state.update(
                {
                    "last_run_at": _now().isoformat(timespec="seconds"),
                    "last_error": None,
                    "last_parsed_count": saved,
                    "total_runs": _state["total_runs"] + 1,
                }
            )
            logger.info("Парсинг /best: сохранено %s статей, удалено старых %s", saved, trimmed)
            return {"ok": True, "saved": saved, "trimmed": trimmed, "posts_in_fetch": len(articles)}
        except Exception as exc:  # noqa: BLE001 — ошибка парсинга не должна ломать планировщик
            _state.update({"last_error": str(exc), "last_run_at": _now().isoformat(timespec="seconds")})
            logger.warning("Ошибка парсинга /best: %s", exc)
            return {"ok": False, "error": str(exc)}


def start_scheduler(*, immediate: bool = True) -> dict:
    settings = get_settings()
    scheduler = _get_scheduler()
    if not scheduler.running:
        scheduler.start()

    if scheduler.get_job(JOB_ID) is None:
        trigger = IntervalTrigger(minutes=settings.parse_interval_minutes)
        scheduler.add_job(
            parse_now,
            trigger=trigger,
            id=JOB_ID,
            name="Парсинг pikabu.ru/best",
            replace_existing=True,
            next_run_time=_now() + timedelta(seconds=2) if immediate else None,
            misfire_grace_time=60,
        )
    _state["running"] = True
    return status()


def stop_scheduler() -> dict:
    scheduler = _scheduler
    if scheduler and scheduler.get_job(JOB_ID) is not None:
        scheduler.remove_job(JOB_ID)
    _state["running"] = False
    return status()


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _state["running"] = False
    _scheduler = None


def is_running() -> bool:
    scheduler = _scheduler
    return bool(scheduler and scheduler.running and scheduler.get_job(JOB_ID) is not None)


def next_run_at() -> str | None:
    scheduler = _scheduler
    if not scheduler:
        return None
    job = scheduler.get_job(JOB_ID)
    if job is None or job.next_run_time is None:
        return None
    return job.next_run_time.astimezone(timezone.utc).isoformat(timespec="seconds")


def status() -> dict:
    settings = get_settings()
    return {
        "running": is_running(),
        "interval_minutes": settings.parse_interval_minutes,
        "next_run_at": next_run_at(),
        "last_run_at": _state["last_run_at"],
        "last_error": _state["last_error"],
        "last_parsed_count": _state["last_parsed_count"],
        "total_runs": _state["total_runs"],
    }
