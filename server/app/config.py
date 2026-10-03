"""Загрузка конфигурации сервера: .env + server/config.json."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT_DIR / "server"
CONFIG_PATH = SERVER_DIR / "config.json"

load_dotenv(ROOT_DIR / ".env")


def _env_list(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class RagSettings:
    """Параметры RAG-пайплайна: чанкинг pikabu-txt.md + эмбеддинги ollama + индексы."""

    source_file: Path
    output_dir: Path
    ollama_base_url: str
    embedding_model: str
    min_tokens: int
    max_tokens: int
    overlap_tokens: int
    chars_per_token: float
    min_chunk_tokens: int
    embed_batch_size: int
    embed_timeout_sec: float
    chat_top_k: int


def _resolve_path(path_value: str) -> Path:
    """Абсолютные пути — как есть, относительные — от корня проекта."""
    path = Path(path_value)
    return path if path.is_absolute() else (ROOT_DIR / path)


def _load_rag(raw: dict) -> RagSettings:
    rag = raw.get("rag", {})
    return RagSettings(
        source_file=_resolve_path(str(rag.get("source_file", "pikabu-txt.md"))),
        output_dir=_resolve_path(str(rag.get("output_dir", "server/data/rag"))),
        ollama_base_url=str(rag.get("ollama_base_url", "http://127.0.0.1:11434")).rstrip("/"),
        embedding_model=str(rag.get("embedding_model", "qwen3-embedding:0.6b")),
        min_tokens=int(rag.get("min_tokens", 500)),
        max_tokens=int(rag.get("max_tokens", 1000)),
        overlap_tokens=int(rag.get("overlap_tokens", 150)),
        chars_per_token=float(rag.get("chars_per_token", 3.0)),
        min_chunk_tokens=int(rag.get("min_chunk_tokens", 50)),
        embed_batch_size=int(rag.get("embed_batch_size", 16)),
        embed_timeout_sec=float(rag.get("embed_timeout_sec", 300)),
        chat_top_k=int(rag.get("chat_top_k", 4)),
    )


@dataclass(frozen=True)
class Settings:
    # LLM
    deepseek_api_key: str
    deepseek_model: str
    deepseek_base_url: str

    # HTTP
    host: str
    port: int
    cors_origins: list[str]

    # Парсинг
    parse_interval_minutes: int
    max_articles: int
    posts_per_fetch: int
    pikabu_best_url: str
    pikabu_themes_url: str
    pikabu_base_url: str
    theme_cache_ttl_sec: int
    excluded_themes: list[str]
    autostart_parsing: bool
    max_post_age_hours: int
    auto_summary_after_parse: bool
    parse_timeout_sec: float
    request_delay_sec: float

    # Чат
    chat_max_iterations: int
    chat_history_limit: int
    chat_rate_limit_per_minute: int
    chat_max_message_chars: int

    # Внешние MCP-серверы
    allowed_screenshot_hosts: list[str]
    external_mcp_servers: list[dict]

    # Пути
    database_path: Path
    summaries_dir: Path

    # RAG
    rag: RagSettings

    def public_config(self) -> dict:
        """Конфигурация без секретов — её отдаём в веб-клиент."""
        return {
            "parse_interval_minutes": self.parse_interval_minutes,
            "max_articles": self.max_articles,
            "posts_per_fetch": self.posts_per_fetch,
            "pikabu_best_url": self.pikabu_best_url,
            "pikabu_themes_url": self.pikabu_themes_url,
            "theme_cache_ttl_sec": self.theme_cache_ttl_sec,
            "excluded_themes": self.excluded_themes,
            "autostart_parsing": self.autostart_parsing,
            "max_post_age_hours": self.max_post_age_hours,
            "auto_summary_after_parse": self.auto_summary_after_parse,
            "model": self.deepseek_model,
            "llm_configured": bool(self.deepseek_api_key),
            "chat_max_iterations": self.chat_max_iterations,
            "chat_rate_limit_per_minute": self.chat_rate_limit_per_minute,
            "chat_max_message_chars": self.chat_max_message_chars,
            "allowed_screenshot_hosts": self.allowed_screenshot_hosts,
            "external_mcp_servers": [
                {
                    "name": server.get("name"),
                    "description": server.get("description"),
                    "enabled_by_default": bool(server.get("enabled_by_default", True)),
                }
                for server in self.external_mcp_servers
            ],
            "rag": {
                "source_file": str(self.rag.source_file),
                "ollama_base_url": self.rag.ollama_base_url,
                "embedding_model": self.rag.embedding_model,
                "min_tokens": self.rag.min_tokens,
                "max_tokens": self.rag.max_tokens,
                "chat_top_k": self.rag.chat_top_k,
            },
        }


def _load_file() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    raw = _load_file()

    return Settings(
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip(),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip(),
        host=os.getenv("HOST", "127.0.0.1").strip(),
        port=int(os.getenv("PORT", "8000")),
        cors_origins=_env_list("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"),
        parse_interval_minutes=int(raw.get("parse_interval_minutes", 30)),
        max_articles=int(raw.get("max_articles", 200)),
        posts_per_fetch=int(raw.get("posts_per_fetch", 8)),
        pikabu_best_url=str(raw.get("pikabu_best_url", "https://pikabu.ru/best")),
        pikabu_themes_url=str(raw.get("pikabu_themes_url", "https://pikabu.ru/themes")),
        pikabu_base_url=str(raw.get("pikabu_base_url", "https://pikabu.ru")).rstrip("/"),
        theme_cache_ttl_sec=int(raw.get("theme_cache_ttl_sec", 300)),
        excluded_themes=list(raw.get("excluded_themes", [])),
        autostart_parsing=bool(raw.get("autostart_parsing", True)),
        max_post_age_hours=int(raw.get("max_post_age_hours", 48)),
        auto_summary_after_parse=bool(raw.get("auto_summary_after_parse", True)),
        parse_timeout_sec=float(raw.get("parse_timeout_sec", 20)),
        request_delay_sec=float(raw.get("request_delay_sec", 1.0)),
        chat_max_iterations=int(raw.get("chat_max_iterations", 16)),
        chat_history_limit=int(raw.get("chat_history_limit", 20)),
        chat_rate_limit_per_minute=int(raw.get("chat_rate_limit_per_minute", 20)),
        chat_max_message_chars=int(raw.get("chat_max_message_chars", 4000)),
        allowed_screenshot_hosts=list(raw.get("allowed_screenshot_hosts", ["pikabu.ru"])),
        external_mcp_servers=list(raw.get("external_mcp_servers", [])),
        database_path=_resolve_path(str(raw.get("database_path", "server/data/pikabu.db"))),
        summaries_dir=_resolve_path(str(raw.get("summaries_dir", "server/data/summaries"))),
        rag=_load_rag(raw),
    )
