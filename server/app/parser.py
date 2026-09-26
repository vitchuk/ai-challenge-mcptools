"""Парсер pikabu.ru: лента /best и страницы тем /themes/<slug>."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .config import get_settings

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

MAX_BODY_CHARS = 2000
_VIDEO_HOST_RE = re.compile(r"(youtube\.com|youtu\.be|vk\.com/video|vkvideo|rutube\.ru|coub\.com)", re.I)

_theme_cache: dict[str, tuple[float, list[dict]]] = {}


class ParserError(RuntimeError):
    """Ошибка загрузки/разбора страницы pikabu."""


async def fetch_html(url: str, *, retries: int = 2) -> str:
    settings = get_settings()
    last_error: Exception | None = None
    async with httpx.AsyncClient(
        headers=HEADERS,
        timeout=settings.parse_timeout_sec,
        follow_redirects=True,
    ) as client:
        for attempt in range(retries + 1):
            try:
                response = await client.get(url)
                if response.status_code == 200:
                    return response.text
                last_error = ParserError(f"HTTP {response.status_code} для {url}")
            except httpx.HTTPError as exc:  # сетевые ошибки, таймауты
                last_error = exc
            if attempt < retries:
                await asyncio.sleep(settings.request_delay_sec * (attempt + 1))
    raise ParserError(f"Не удалось загрузить {url}: {last_error}")


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value.replace("\u2060", "")).strip()


def _as_int(value: str | None) -> int | None:
    if value is None:
        return None
    digits = re.sub(r"[^\d-]", "", value)
    return int(digits) if digits not in ("", "-") else None


def _extract_images(article) -> list[str]:
    result: list[str] = []
    for img in article.select("img.story-image__image, .story-image__image"):
        for attr in ("data-large-image", "data-src", "src"):
            src = img.get(attr)
            if src:
                url = src.strip()
                if url and url not in result:
                    result.append(url)
                break
    return result


def _extract_videos(article) -> list[str]:
    result: list[str] = []
    for elem in article.select("video[src], video source[src], iframe[src]"):
        src = (elem.get("src") or "").strip()
        if src and src not in result:
            result.append(src)
    for link in article.select("a[href]"):
        href = (link.get("href") or "").strip()
        if href and _VIDEO_HOST_RE.search(href) and href not in result:
            result.append(href)
    return result


def _extract_tags(article) -> list[str]:
    result: list[str] = []
    for tag in article.select(".story__tags a, a[data-tag]"):
        name = _clean_text(tag.get("data-tag") or tag.get_text(" ", strip=True))
        if name and name not in result:
            result.append(name)
    return result


def _extract_theme(article) -> str | None:
    link = article.select_one("a[href^='/themes/'], a[href*='pikabu.ru/themes/']")
    if not link:
        return None
    name = _clean_text(link.get_text(" ", strip=True))
    return name or None


def _parse_article(article, base_url: str) -> dict | None:
    story_id = _as_int(article.get("data-story-id"))
    title_link = article.select_one("a.story__title-link")
    if not story_id or not title_link:
        return None

    title = _clean_text(title_link.get_text(" ", strip=True))
    href = (title_link.get("href") or "").strip()
    url = urljoin(base_url + "/", href)

    content = article.select_one(".story__content")
    body_text = _clean_text(content.get_text(" ", strip=True)) if content else ""
    if len(body_text) > MAX_BODY_CHARS:
        body_text = body_text[:MAX_BODY_CHARS].rstrip() + "…"

    published_at = None
    datetime_el = article.select_one(".story__datetime[datetime]")
    if datetime_el:
        published_at = datetime_el.get("datetime")
    elif article.get("data-timestamp"):
        ts = _as_int(article.get("data-timestamp"))
        if ts:
            published_at = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")

    rating = _as_int(article.get("data-rating"))
    if rating is None:
        rating_el = article.select_one(".story__rating-count")
        rating = _as_int(rating_el.get_text(" ", strip=True)) if rating_el else None

    return {
        "story_id": story_id,
        "title": title,
        "url": url,
        "author": _clean_text(article.get("data-author-name")) or None,
        "theme": _extract_theme(article),
        "tags": _extract_tags(article),
        "rating": rating,
        "comments_count": _as_int(article.get("data-comments")),
        "body_text": body_text,
        "images": _extract_images(article),
        "videos": _extract_videos(article),
        "published_at": published_at,
    }


def parse_stories(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    stories: list[dict] = []
    for article in soup.select("article[data-story-id]"):
        parsed = _parse_article(article, base_url)
        if parsed:
            stories.append(parsed)
    return stories


async def fetch_best(limit: int | None = None) -> list[dict]:
    """Загружает ленту /best («лучшее за сегодня») и отбрасывает посты старше N часов."""
    settings = get_settings()
    html = await fetch_html(settings.pikabu_best_url)
    stories = parse_stories(html, settings.pikabu_base_url)
    stories = [story for story in stories if _is_recent(story.get("published_at"), settings.max_post_age_hours)]
    if limit:
        stories = stories[:limit]
    if not stories:
        raise ParserError(
            f"Страница /best загружена, но нет постов свежее {settings.max_post_age_hours} ч"
        )
    return stories


def _is_recent(published_at: str | None, max_age_hours: int) -> bool:
    """Страховка «за сегодня»: отбрасываем посты старше max_age_hours (если дата известна)."""
    if not published_at:
        return True
    try:
        published = datetime.fromisoformat(published_at)
    except ValueError:
        return True
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - published
    return age.total_seconds() <= max_age_hours * 3600


async def fetch_theme(slug: str, limit: int = 20, use_cache: bool = True) -> list[dict]:
    """Загружает посты темы /themes/<slug> с коротким кэшем."""
    settings = get_settings()
    now = time.monotonic()
    if use_cache:
        cached = _theme_cache.get(slug)
        if cached and now - cached[0] < settings.theme_cache_ttl_sec:
            return cached[1][:limit]

    url = f"{settings.pikabu_base_url}/themes/{slug}"
    html = await fetch_html(url)
    stories = parse_stories(html, settings.pikabu_base_url)
    if not stories:
        raise ParserError(f"Тема '{slug}' не содержит постов или не существует")
    _theme_cache[slug] = (now, stories)
    return stories[:limit]


def clear_theme_cache() -> None:
    _theme_cache.clear()


def hostname_allowed(url: str) -> bool:
    """Разрешаем только pikabu.ru — защита от SSRF."""
    host = urlparse(url).hostname or ""
    return host == "pikabu.ru" or host.endswith(".pikabu.ru")
