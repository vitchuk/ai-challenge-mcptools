"""MCP-сервер (официальный Python SDK, Streamable HTTP)."""

from __future__ import annotations

import logging

from mcp.server.mcpserver import MCPServer

from . import tools

logger = logging.getLogger(__name__)

mcp = MCPServer(
    name="pikabu-mcp",
    title="Pikabu MCP Server",
    description="MCP-сервер: парсинг pikabu.ru/best, тулы тем, саммаризация и управление парсингом.",
    instructions=(
        "Тулы для работы с pikabu.ru: get_saved_articles, get_theme_<тема>, "
        "summarize_best_posts, save_summary, start_parsing_pikabu, stop_parsing_pikabu."
    ),
)

_registered = False


def register_tools(themes: list[dict]) -> list[dict]:
    global _registered
    if not _registered:
        tools.register_all(mcp, themes)
        _registered = True
        logger.info("Зарегистрировано тулов: %s", len(tools.REGISTRY))
    return themes


def build_app():
    """ASGI-приложение MCP (Streamable HTTP) для монтирования в FastAPI."""
    return mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )
