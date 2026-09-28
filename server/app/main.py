"""Точка входа: FastAPI + MCP (Streamable HTTP) + статика собранного Vue-клиента."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import db, mcp_manager, mcp_server, scheduler
from .api import router as api_router
from .config import ROOT_DIR, get_settings
from .themes import load_themes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    db.init_db()
    themes = await load_themes()
    mcp_server.register_tools(themes)
    app.state.themes = themes
    logger.info("Тем загружено: %s", len(themes))

    mcp_manager.manager.configure(settings.external_mcp_servers)
    await mcp_manager.manager.startup()

    async with mcp_server.mcp.session_manager.run():
        if settings.autostart_parsing:
            scheduler.start_scheduler()
            logger.info(
                "Парсинг запущен автоматически (каждые %s мин)", settings.parse_interval_minutes
            )
        try:
            yield
        finally:
            await mcp_manager.manager.shutdown()
            scheduler.shutdown_scheduler()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Pikabu MCP Server", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix="/api")

    # MCP Streamable HTTP по пути /mcp
    for route in mcp_server.build_app().routes:
        app.router.routes.append(route)

    dist_dir = ROOT_DIR / "client" / "dist"
    if dist_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="client")
        logger.info("Статика клиента подключена из %s", dist_dir)
    else:
        logger.info("client/dist не найден — фронтенд запускайте через Vite (npm run dev)")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    _settings = get_settings()
    uvicorn.run("app.main:app", host=_settings.host, port=_settings.port)
