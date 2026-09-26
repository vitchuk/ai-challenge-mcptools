"""REST API для веб-клиента."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel, Field

from . import chat, db, mcp_server, scheduler, tools
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

    return {
        "mcp": {
            "connected": mcp_ok,
            "endpoint": "/mcp",
            "transport": "streamable-http",
            "tools_count": len(tools.REGISTRY),
        },
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
    info = tools.tools_info()
    return {"count": len(info), "tools": info}


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
    """Удаляет все статьи из БД и все сохранённые саммари."""
    cleared_articles = db.clear_articles()
    cleared_summaries = tools.clear_summaries()
    scheduler.reset_parse_stats()
    logger.info("Очистка данных: статей %s, саммари %s", cleared_articles, cleared_summaries)
    return {"cleared_articles": cleared_articles, "cleared_summaries": cleared_summaries}


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
