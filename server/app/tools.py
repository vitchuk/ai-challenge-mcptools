"""Реестр MCP-тулов: единый источник правды для MCP-сервера и LLM-агента."""

from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from . import db, deepseek, parser, scheduler
from .config import ROOT_DIR, get_settings
from .themes import tool_name_for

logger = logging.getLogger(__name__)

ToolCallable = Callable[..., Awaitable[str]]

REGISTRY: dict[str, dict[str, Any]] = {}

_last_summary: dict | None = None
_last_summary_dir: Path | None = None  # текущая папка саммари (для скриншотов)


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _register(
    name: str,
    description: str,
    parameters: dict,
    fn: ToolCallable,
    short_description: str | None = None,
) -> None:
    REGISTRY[name] = {
        "name": name,
        "description": description,
        "short_description": short_description,
        "parameters": parameters,
        "callable": fn,
    }


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def _post_brief(post: dict) -> dict:
    return {
        "title": post.get("title"),
        "url": post.get("url"),
        "author": post.get("author"),
        "theme": post.get("theme"),
        "rating": post.get("rating"),
        "comments_count": post.get("comments_count"),
        "published_at": post.get("published_at"),
        "tags": post.get("tags", []),
        "body_text": post.get("body_text", ""),
        "images": post.get("images", []),
        "videos": post.get("videos", []),
    }


def _collect_media(articles: list[dict]) -> tuple[list[str], list[str]]:
    images: list[str] = []
    videos: list[str] = []
    for article in articles:
        for url in article.get("images", []):
            if url and url not in images:
                images.append(url)
        for url in article.get("videos", []):
            if url and url not in videos:
                videos.append(url)
    return images, videos


# --------------------------------------------------------------------------- #
# Базовые тулы
# --------------------------------------------------------------------------- #

async def get_saved_articles(limit: int = 20) -> str:
    articles = db.get_articles(limit=max(1, min(int(limit), 200)))
    return _json(
        {
            "count": len(articles),
            "articles": [_post_brief(article) for article in articles],
        }
    )


async def summarize_best_posts(count: int = 10) -> str:
    """Саммари последних N статей из /best (создаёт папку саммари под скриншоты)."""
    count = max(1, min(int(count), 50))
    articles = db.get_articles_for_summary(count)
    if not articles:
        return _json(
            {
                "error": "В базе нет статей — нечего саммаризировать.",
                "hint": "Запустите парсинг (тул start_parsing_pikabu или кнопка в UI).",
            }
        )
    try:
        summary = await _summarize_articles(articles)
    except deepseek.LLMError as exc:
        return _json({"error": str(exc)})
    return _json(summary)


def _build_prompt(articles: list[dict]) -> tuple[str, str]:
    blocks = []
    for index, article in enumerate(articles, start=1):
        blocks.append(
            f"{index}. {article['title']}\n"
            f"   Автор: {article.get('author') or '—'}; тема: {article.get('theme') or '—'}; "
            f"рейтинг: {article.get('rating')}; комментарии: {article.get('comments_count')}\n"
            f"   URL: {article.get('url')}\n"
            f"   Текст: {article.get('body_text') or '(без текста)'}"
        )
    system_prompt = (
        "Ты — редактор дайджеста постов Pikabu. По списку постов сделай краткое саммари. "
        "Отвечай строго в формате JSON без пояснений и без markdown-обёртки: "
        '{"title": "краткий цепляющий заголовок дайджеста", "summary": "связный текст саммари на русском"}'
    )
    user_prompt = (
        f"Вот {len(articles)} постов категории /best. Сделай дайджест:\n\n" + "\n\n".join(blocks)
    )
    return system_prompt, user_prompt


async def _summarize_articles(articles: list[dict], *, folder: bool = True) -> dict:
    """Саммари статей через LLM.

    folder=True (саммари из чата): создаёт папку summary_<ГГГГММДД_ЧЧММСС>/, пишет summary.json,
    делает её текущей — туда маршрутизируются скриншоты.
    folder=False (автосаммари после парсинга): пишет плоский summary_auto_<ГГГГММДД_ЧЧММСС>.json,
    папку не создаёт и маршрут скриншотов (_last_summary_dir) не перехватывает.
    """
    global _last_summary, _last_summary_dir
    system_prompt, user_prompt = _build_prompt(articles)
    raw = await deepseek.complete_text(system_prompt, user_prompt, temperature=0.4, max_tokens=2500)
    title, summary = _parse_summary(raw, fallback_title=articles[0]["title"])
    images, videos = _collect_media(articles)
    posts = [{"title": a.get("title"), "url": a.get("url")} for a in articles]

    settings = get_settings()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    data = {
        "title": title,
        "summary": summary,
        "images": images,
        "videos": videos,
        "posts": posts,
        "source_count": len(articles),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    if folder:
        folder_path = settings.summaries_dir / f"summary_{timestamp}"
        folder_path.mkdir(parents=True, exist_ok=True)
        summary_file = folder_path / "summary.json"
        summary_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        _last_summary_dir = folder_path
    else:
        settings.summaries_dir.mkdir(parents=True, exist_ok=True)
        summary_file = settings.summaries_dir / f"summary_auto_{timestamp}.json"
        summary_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    _last_summary = {**data, "folder": _rel(folder_path) if folder else None, "file": _rel(summary_file)}
    return _last_summary


async def summarize_articles(articles: list[dict]) -> dict:
    """Автосаммари после парсинга (планировщик): плоский JSON, без папки."""
    return await _summarize_articles(articles, folder=False)


def current_summary_dir():
    """Текущая папка саммари (куда складывать скриншоты) или None."""
    return _last_summary_dir


def _parse_summary(raw: str, *, fallback_title: str) -> tuple[str, str]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned[cleaned.find("{") :] if "{" in cleaned else cleaned
    try:
        data = json.loads(cleaned)
        title = str(data.get("title") or fallback_title).strip()
        summary = str(data.get("summary") or "").strip()
        if summary:
            return title, summary
    except (json.JSONDecodeError, AttributeError):
        logger.warning("Не удалось распарсить JSON саммаризации, использую сырой текст")
    return fallback_title, raw.strip()


async def save_summary(format: str = "txt") -> str:
    """Сохраняет последний результат саммаризации в .txt или .json."""
    if (_last_summary is None):
        return _json(
            {
                "error": "Нет результата саммаризации для сохранения.",
                "hint": "Сначала вызовите тул summarize_best_posts.",
            }
        )
    try:
        return _json(_save_last_summary(format))
    except ValueError as exc:
        return _json({"error": str(exc)})


def _save_last_summary(format: str) -> dict:
    fmt = (format or "txt").strip().lower()
    if fmt not in ("txt", "json"):
        raise ValueError("Недопустимый формат. Используйте 'txt' или 'json'.")
    if _last_summary is None:
        raise ValueError("Нет результата саммаризации для сохранения.")

    settings = get_settings()
    target_dir = _last_summary_dir if _last_summary_dir is not None else settings.summaries_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"summary.{fmt}" if _last_summary_dir is not None else f"summary_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.{fmt}"
    path = target_dir / filename

    payload = {k: v for k, v in _last_summary.items() if k not in ("folder", "file")}
    if fmt == "json":
        content = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        images = payload.get("images", [])
        videos = payload.get("videos", [])
        lines = [
            f"Заголовок: {payload.get('title', '')}",
            f"Дата: {payload.get('created_at', '')}",
            f"Постов в саммари: {payload.get('source_count', 0)}",
            "",
            payload.get("summary", ""),
            "",
            f"Изображения ({len(images)}):",
            *[f"- {url}" for url in images],
            "",
            f"Видео ({len(videos)}):",
            *[f"- {url}" for url in videos],
            "",
        ]
        content = "\n".join(lines)

    path.write_text(content, encoding="utf-8")
    return {
        "saved": True,
        "format": fmt,
        "file": _rel(path),
        "folder": _rel(target_dir),
        "bytes": len(content.encode("utf-8")),
    }


def save_last_summary(format: str = "json") -> dict:
    """Публичная обёртка для автосохранения саммари (используется планировщиком)."""
    return _save_last_summary(format)


def clear_summaries() -> int:
    """Удаляет все папки/файлы саммари и сбрасывает состояние. Возвращает число удалённых объектов."""
    global _last_summary, _last_summary_dir
    settings = get_settings()
    removed = 0
    if settings.summaries_dir.is_dir():
        for path in sorted(settings.summaries_dir.glob("summary_*")):
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                removed += 1
            except OSError as exc:
                logger.warning("Не удалось удалить %s: %s", path, exc)
    _last_summary = None
    _last_summary_dir = None
    return removed


def get_latest_summary() -> dict:
    """Самый свежий саммари: из папок summary_<ts>/summary.json и плоских summary_*[_auto]_<ts>.json."""
    settings = get_settings()
    if not settings.summaries_dir.is_dir():
        return {"exists": False, "file": None, "folder": None, "summary": None}

    candidates: list[tuple[str, Path, Path | None]] = []  # (timestamp, summary_file, folder|None)
    for folder in settings.summaries_dir.glob("summary_*"):
        if not folder.is_dir():
            continue
        summary_file = folder / "summary.json"
        if summary_file.is_file():
            candidates.append((_name_timestamp(folder.name), summary_file, folder))
    for file in settings.summaries_dir.glob("summary_*.json"):
        candidates.append((_name_timestamp(file.name), file, None))

    empty = {"exists": False, "file": None, "folder": None, "summary": None}
    if not candidates:
        return empty

    _, latest_file, latest_folder = max(candidates, key=lambda item: (item[0], item[1].stat().st_mtime))
    data = _read_summary_json(latest_file)
    if data is None:
        return empty
    return {
        "exists": True,
        "file": _rel(latest_file),
        "folder": _rel(latest_folder) if latest_folder else None,
        "summary": data,
    }


def _name_timestamp(name: str) -> str:
    """Достаёт ГГГГММДД_ЧЧММСС из имени summary_..._ / summary_auto_...."""
    match = re.search(r"(\d{8}_\d{6})", name)
    return match.group(1) if match else ""


def _read_summary_json(path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Не удалось прочитать саммари %s", path)
        return None


async def start_parsing_pikabu() -> str:
    return _json(scheduler.start_scheduler())


async def stop_parsing_pikabu() -> str:
    return _json(scheduler.stop_scheduler())


# --------------------------------------------------------------------------- #
# Тулы тем
# --------------------------------------------------------------------------- #

def _make_theme_tool(slug: str, title: str) -> ToolCallable:
    async def get_theme(limit: int = 20) -> str:
        try:
            posts = await parser.fetch_theme(slug, limit=max(1, min(int(limit), 50)))
        except parser.ParserError as exc:
            return _json({"error": str(exc), "theme": slug})
        return _json(
            {
                "theme": slug,
                "theme_title": title,
                "count": len(posts),
                "posts": [_post_brief(post) for post in posts],
            }
        )

    get_theme.__name__ = tool_name_for(slug)
    get_theme.__doc__ = f"Последние посты темы «{title}» (https://pikabu.ru/themes/{slug})."
    return get_theme


# --------------------------------------------------------------------------- #
# Регистрация
# --------------------------------------------------------------------------- #

def register_core_tools() -> None:
    _register(
        "get_saved_articles",
        "Возвращает статьи, сохранённые в SQLite (спарсенные с pikabu.ru/best). "
        "Используй, когда нужно показать содержимое базы.",
        {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Сколько статей вернуть (1-200).", "default": 20}
            },
            "required": [],
        },
        get_saved_articles,
    )
    _register(
        "summarize_best_posts",
        "Делает саммари последних N статей из сохранённой ленты pikabu.ru/best и создаёт папку "
        "саммари. Возвращает JSON: заголовок, текст саммари, images[], videos[] и posts[] (title+url "
        "разбираемых постов). Папка (поле folder) становится текущей: скриншоты из внешних "
        "MCP-серверов автоматически сохраняются в неё. Результат доступен тулу save_summary.",
        {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "description": "Сколько последних статей саммаризировать.", "default": 10}
            },
            "required": [],
        },
        summarize_best_posts,
    )
    _register(
        "save_summary",
        "Сохраняет результат последнего вызова summarize_best_posts в файл на сервере. "
        "Формат 'txt' — читаемый текст, 'json' — {title, summary, images[], videos[]}.",
        {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "description": "Формат файла: txt или json.",
                    "enum": ["txt", "json"],
                    "default": "txt",
                }
            },
            "required": [],
        },
        save_summary,
    )
    _register(
        "start_parsing_pikabu",
        "Запускает cron-парсинг pikabu.ru/best по расписанию из конфига "
        "(первый прогон — сразу после запуска).",
        {"type": "object", "properties": {}, "required": []},
        start_parsing_pikabu,
    )
    _register(
        "stop_parsing_pikabu",
        "Останавливает cron-парсинг pikabu.ru/best. Уже сохранённые статьи остаются в базе.",
        {"type": "object", "properties": {}, "required": []},
        stop_parsing_pikabu,
    )


def register_theme_tools(themes: list[dict]) -> None:
    for theme in themes:
        slug = theme["slug"]
        title = theme["title"]
        name = tool_name_for(slug)
        _register(
            name,
            f"Последние посты с pikabu.ru по теме «{title}» (https://pikabu.ru/themes/{slug}). "
            "Возвращает заголовки, авторов, рейтинг, текст и ссылки.",
            {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Сколько постов вернуть (1-50).", "default": 20}
                },
                "required": [],
            },
            _make_theme_tool(slug, title),
            short_description=f"Посты темы «{title}»",
        )


def register_all(mcp_server: Any, themes: list[dict]) -> list[dict]:
    """Регистрирует все тулы в реестре и в MCP-сервере. Возвращает список тем."""
    if not REGISTRY:
        register_core_tools()
        register_theme_tools(themes)

    for entry in REGISTRY.values():
        mcp_server.add_tool(entry["callable"], name=entry["name"], description=entry["description"])
    return themes


def openai_tools_schema() -> list[dict]:
    """Схемы тулов в формате OpenAI/DeepSeek function calling."""
    return [
        {
            "type": "function",
            "function": {
                "name": entry["name"],
                "description": entry["description"],
                "parameters": entry["parameters"],
            },
        }
        for entry in REGISTRY.values()
    ]


def tools_info() -> list[dict]:
    """Метаданные тулов для веб-клиента (/api/tools, команда /tools)."""
    return [
        {
            "name": entry["name"],
            "description": entry["description"],
            "short_description": entry.get("short_description"),
            "parameters": entry["parameters"],
        }
        for entry in REGISTRY.values()
    ]


async def call_tool(name: str, arguments: dict) -> str:
    entry = REGISTRY.get(name)
    if entry is None:
        return _json({"error": f"Неизвестный тул: {name}"})
    try:
        result = await entry["callable"](**(arguments or {}))
    except TypeError as exc:
        return _json({"error": f"Некорректные аргументы тула {name}: {exc}"})
    except Exception as exc:  # noqa: BLE001 — ошибки тулов не должны ронять чат
        logger.exception("Ошибка выполнения тула %s", name)
        return _json({"error": f"Ошибка тула {name}: {exc}"})
    return result if isinstance(result, str) else _json(result)


def last_summary() -> dict | None:
    return _last_summary
