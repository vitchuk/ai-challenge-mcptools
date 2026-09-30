"""REST API для веб-клиента."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from . import chat, db, mcp_manager, mcp_server, rag, scheduler, tools
from .config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(default="", description="Сообщение пользователя")
    session_id: str | None = Field(default=None, max_length=128)


@router.get("/status")
async def get_status() -> dict:
    settings = get_settings()
    mcp_ok = False
    try:
        await mcp_server.mcp.list_tools()
        mcp_ok = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("MCP health-check failed: %s", exc)

    builtin = {
        "name": "pikabu",
        "description": "Встроенный сервер: тулы pikabu (статьи, темы, саммари, парсинг)",
        "builtin": True,
        "enabled": True,
        "connected": mcp_ok,
        "tools_count": len(tools.REGISTRY),
        "tools": list(tools.REGISTRY.keys()),
        "last_error": None,
        "output_dir": None,
    }
    servers = [builtin] + mcp_manager.manager.status()

    return {
        "mcp": {
            "connected": mcp_ok,
            "endpoint": "/mcp",
            "transport": "streamable-http",
            "tools_count": len(tools.REGISTRY),
        },
        "servers": servers,
        "parsing": scheduler.status(),
        "articles_count": db.count_articles(),
        "last_parsed_at": db.last_parsed_at(),
        "llm": {
            "model": settings.deepseek_model,
            "configured": bool(settings.deepseek_api_key),
        },
    }


@router.get("/config")
async def get_config() -> dict:
    return get_settings().public_config()


@router.get("/articles")
async def get_articles(limit: int = Query(default=100, ge=1, le=500)) -> dict:
    articles = db.get_articles(limit=limit)
    return {"count": len(articles), "articles": articles}


@router.get("/tools")
async def get_tools() -> dict:
    builtin = [{**entry, "server": "pikabu"} for entry in tools.tools_info()]
    external = mcp_manager.manager.external_tools_info()
    all_tools = builtin + external
    return {"count": len(all_tools), "tools": all_tools}


@router.get("/mcp-servers")
async def get_mcp_servers() -> dict:
    return {"servers": mcp_manager.manager.status()}


@router.post("/mcp-servers/{name}/enable")
async def enable_mcp_server(name: str) -> dict:
    try:
        return await mcp_manager.manager.set_enabled(name, True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Неизвестный MCP-сервер: {name}") from exc


@router.post("/mcp-servers/{name}/disable")
async def disable_mcp_server(name: str) -> dict:
    try:
        return await mcp_manager.manager.set_enabled(name, False)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Неизвестный MCP-сервер: {name}") from exc


@router.get("/themes")
async def get_themes(request: Request) -> dict:
    themes = getattr(request.app.state, "themes", [])
    return {"count": len(themes), "themes": themes}


@router.post("/parsing/start")
async def start_parsing() -> dict:
    return scheduler.start_scheduler()


@router.post("/parsing/stop")
async def stop_parsing() -> dict:
    return scheduler.stop_scheduler()


@router.post("/parsing/run-now")
async def run_parsing_now() -> dict:
    return await scheduler.parse_now()


@router.post("/parsing/clear-data")
async def clear_data() -> dict:
    """Удаляет все статьи из БД, все саммари и содержимое output-папок внешних MCP-серверов."""
    cleared_articles = db.clear_articles()
    cleared_summaries = tools.clear_summaries()
    cleared_mcp_outputs = mcp_manager.manager.clear_output_dirs()
    scheduler.reset_parse_stats()
    logger.info(
        "Очистка данных: статей %s, саммари %s, файлов вывода MCP %s",
        cleared_articles,
        cleared_summaries,
        cleared_mcp_outputs,
    )
    return {
        "cleared_articles": cleared_articles,
        "cleared_summaries": cleared_summaries,
        "cleared_mcp_outputs": cleared_mcp_outputs,
    }


@router.get("/summary/latest")
async def latest_summary() -> dict:
    return tools.get_latest_summary()


@router.post("/chat")
async def post_chat(
    payload: ChatRequest,
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
) -> dict:
    session_id = (payload.session_id or x_session_id or "default")[:128]
    return await chat.run_chat(session_id, payload.message)


@router.post("/chat/reset")
async def reset_chat(
    payload: ChatRequest | None = None,
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
) -> dict:
    session_id = ((payload.session_id if payload else None) or x_session_id or "default")[:128]
    chat.reset_session(session_id)
    return {"ok": True, "session_id": session_id}


@router.get("/rag/strategies")
async def get_rag_strategies() -> dict:
    """Собранные RAG-индексы по стратегиям чанкинга (для переключения стратегий в UI)."""
    return {"strategies": rag.list_indexes()}


@router.get("/rag/strategies/{strategy}")
async def get_rag_strategy_chunks(
    strategy: str, limit: int = Query(default=50, ge=1, le=500)
) -> dict:
    """Чанки конкретной стратегии (без векторов)."""
    index = rag.load_index(strategy)
    if index is None:
        raise HTTPException(status_code=404, detail=f"Индекс стратегии '{strategy}' не собран")
    chunks = index.get("chunks", [])
    return {
        "strategy": strategy,
        "description": index.get("description"),
        "params": index.get("params"),
        "source": index.get("source"),
        "embedding": index.get("embedding"),
        "built_at": index.get("built_at"),
        "chunks_total": len(chunks),
        "chunks": chunks[:limit],
    }
