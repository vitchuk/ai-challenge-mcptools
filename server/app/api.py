"""REST API для веб-клиента."""

from __future__ import annotations

import json
import logging
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import chat, db, llm, llm_log, mcp_manager, mcp_server, rag, rag_pipeline, scheduler, tools
from .config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()


class RagOptionsPayload(BaseModel):
    """Параметры стратегии поиска RAG (retrieval pipeline) для вкладки «Чат»."""

    strategy: str = Field(default="baseline", max_length=64)
    top_k: int | None = Field(default=None, ge=1, le=100)
    top_k_before: int | None = Field(default=None, ge=1, le=100)
    top_k_after: int | None = Field(default=None, ge=1, le=100)
    top_k_final: int | None = Field(default=None, ge=1, le=100)
    similarity_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    reranker_threshold: float | None = Field(default=None, ge=0.0, le=1.0)

    def to_options(self) -> rag_pipeline.RetrievalOptions:
        return rag_pipeline.RetrievalOptions(
            strategy=self.strategy,
            top_k=self.top_k,
            top_k_before=self.top_k_before,
            top_k_after=self.top_k_after,
            top_k_final=self.top_k_final,
            similarity_threshold=self.similarity_threshold,
            reranker_threshold=self.reranker_threshold,
        )


class ChatRequest(BaseModel):
    message: str = Field(default="", description="Сообщение пользователя")
    session_id: str | None = Field(default=None, max_length=128)
    rag_strategy: str | None = Field(
        default=None, max_length=64, description="Стратегия RAG для вкладки «Чат»; None — без RAG"
    )
    rag_options: RagOptionsPayload | None = Field(
        default=None,
        description="Стратегия поиска RAG: baseline / query-rewrite / similarity-filter / "
        "query-rewrite-rerank; None — baseline-поведение",
    )
    llm_provider: Literal["deepseek", "ollama"] | None = Field(
        default=None,
        description="Провайдер LLM для чата: deepseek (облако) или ollama (локальная модель)",
    )


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
            "deepseek": {
                "model": settings.deepseek_model,
                "configured": bool(settings.deepseek_api_key),
            },
            "ollama": {
                "model": settings.ollama_chat_model,
                "base_url": settings.ollama_base_url,
                "available": await llm.check_ollama_available(),
            },
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
    rag_options = payload.rag_options.to_options() if payload.rag_options else None
    provider = payload.llm_provider or llm.DEFAULT_PROVIDER
    return await chat.run_chat(
        session_id, payload.message, payload.rag_strategy, rag_options, provider
    )


@router.post("/chat/stream")
async def post_chat_stream(
    payload: ChatRequest,
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
) -> StreamingResponse:
    """Стрим чата (SSE): события thinking / tool / reply."""
    session_id = (payload.session_id or x_session_id or "default")[:128]
    rag_options = payload.rag_options.to_options() if payload.rag_options else None
    provider = payload.llm_provider or llm.DEFAULT_PROVIDER

    async def event_stream():
        async for event in chat.run_chat_stream(
            session_id, payload.message, payload.rag_strategy, rag_options, provider
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/llm-log")
async def get_llm_log(limit: int = Query(default=50, ge=1, le=200)) -> dict:
    """Последние LLM-вызовы (контекст + ответ) для вкладки LOG."""
    entries = llm_log.recent(limit)
    return {"count": len(entries), "entries": entries}


@router.post("/llm-log/clear")
async def clear_llm_log() -> dict:
    return {"cleared": llm_log.clear()}


@router.post("/chat/reset")
async def reset_chat(
    payload: ChatRequest | None = None,
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
) -> dict:
    session_id = ((payload.session_id if payload else None) or x_session_id or "default")[:128]
    chat.reset_session(session_id)
    return {"ok": True, "session_id": session_id}


@router.get("/chat/history")
async def get_chat_history(
    session_id: str | None = Query(default=None, max_length=128),
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
) -> dict:
    """История диалога и память задачи сессии (для восстановления чата в UI)."""
    sid = ((session_id or x_session_id or "default"))[:128]
    return chat.load_session(sid)


@router.get("/chats")
async def get_chats() -> dict:
    """Список сохранённых чатов (заголовок = первый вопрос, свежие сверху)."""
    chats = chat.list_chats()
    return {"count": len(chats), "chats": chats}


@router.post("/chats/{session_id}/delete")
async def delete_chat(session_id: str) -> dict:
    """Удаляет чат целиком (метаданные, история, память задачи). Идемпотентно."""
    sid = session_id[:128]
    chat.reset_session(sid)
    return {"ok": True, "session_id": sid}


@router.get("/rag/strategies")
async def get_rag_strategies() -> dict:
    """Собранные RAG-индексы (чанкинг) + доступные стратегии поиска для UI."""
    return {
        "strategies": rag.list_indexes(),
        "retrieval_strategies": [
            {"id": key, "description": value}
            for key, value in rag_pipeline.RETRIEVAL_STRATEGIES.items()
        ],
    }


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
