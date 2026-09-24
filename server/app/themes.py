"""Список тем pikabu.ru (источник — https://pikabu.ru/themes) и генерация имён тулов."""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from .config import get_settings
from .parser import fetch_html

logger = logging.getLogger(__name__)

# Снимок со страницы https://pikabu.ru/themes — используется как fallback,
# если страницу не удалось загрузить.
FALLBACK_THEMES: list[dict] = [
    {"slug": "politics", "title": "Политика"},
    {"slug": "adult", "title": "18+"},
    {"slug": "games", "title": "Игры"},
    {"slug": "humor", "title": "Юмор"},
    {"slug": "relationships", "title": "Отношения"},
    {"slug": "health", "title": "Здоровье"},
    {"slug": "travel", "title": "Путешествия"},
    {"slug": "sport", "title": "Спорт"},
    {"slug": "hobby", "title": "Хобби"},
    {"slug": "service", "title": "Сервис"},
    {"slug": "nature", "title": "Природа"},
    {"slug": "business", "title": "Бизнес"},
    {"slug": "transport", "title": "Транспорт"},
    {"slug": "talk", "title": "Общение"},
    {"slug": "law", "title": "Юриспруденция"},
    {"slug": "science", "title": "Наука"},
    {"slug": "it", "title": "IT"},
    {"slug": "animals", "title": "Животные"},
    {"slug": "cinema", "title": "Кино и сериалы"},
    {"slug": "economics", "title": "Экономика"},
    {"slug": "cooking", "title": "Кулинария"},
    {"slug": "history", "title": "История"},
    {"slug": "renovation", "title": "Недвижимость и ремонт"},
]


def tool_name_for(slug: str) -> str:
    safe = re.sub(r"[^0-9a-zA-Z_]", "_", slug).strip("_")
    return f"get_theme_{safe}"


async def load_themes() -> list[dict]:
    """Актуальный список тем со страницы /themes, с fallback на встроенный список."""
    settings = get_settings()
    themes: list[dict] = []
    try:
        html = await fetch_html(settings.pikabu_themes_url, retries=1)
        soup = BeautifulSoup(html, "lxml")
        for link in soup.select("a.page-topics__topic[href^='/themes/']"):
            href = link.get("href", "")
            slug = href.rstrip("/").split("/")[-1]
            heading = link.find(["h1", "h2", "h3"])
            title = (heading.get_text(" ", strip=True) if heading else "") or slug
            if slug and all(item["slug"] != slug for item in themes):
                themes.append({"slug": slug, "title": title})
    except Exception as exc:  # noqa: BLE001 — загрузка тем не должна ронять сервер
        logger.warning("Не удалось загрузить список тем pikabu (%s), использую fallback", exc)

    if not themes:
        themes = list(FALLBACK_THEMES)

    excluded = set(get_settings().excluded_themes)
    return [theme for theme in themes if theme["slug"] not in excluded]
