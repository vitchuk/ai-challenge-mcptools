"""Менеджер внешних MCP-серверов: запуск/остановка stdio-клиентов, статус,
вызовы тулов с маршрутизацией скриншотов в папку саммари.

Каждый сервер описан в config.json (external_mcp_servers). Сессия живёт внутри
отдельной asyncio-задачи и удерживается через контекстные менеджеры
`stdio_client` + `ClientSession`; остановка — по asyncio.Event (выход контекста
происходит в той же задаче, которая их открыла — требование anyio).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from .config import ROOT_DIR, get_settings

logger = logging.getLogger(__name__)

SEPARATOR = "__"  # namespace: "<server>__<tool>"
STATE_FILE = ROOT_DIR / "server" / "data" / "mcp_servers_state.json"
STARTUP_TIMEOUT_SEC = 90
CALL_TIMEOUT_SEC = 120  # холодный старт npx/браузера может быть долгим


class ExternalServer:
    """Один внешний MCP-сервер и его фоновая сессия."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.name: str = str(cfg["name"])
        self.description: str = str(cfg.get("description") or "")
        self.command: str = str(cfg.get("command") or "")
        self.args: list[str] = [str(a) for a in cfg.get("args", [])]
        self.enabled_by_default: bool = bool(cfg.get("enabled_by_default", True))
        self._tools_filter = [str(t) for t in cfg.get("tools_filter", [])]
        self._screenshot_tools = {str(t) for t in cfg.get("screenshot_tools", [])}

        output_dir = cfg.get("output_dir")
        output_dir_flag = cfg.get("output_dir_flag")
        if output_dir and output_dir_flag:
            out_path = self._resolve(output_dir)
            out_path.mkdir(parents=True, exist_ok=True)
            self.args = self.args + [str(output_dir_flag), str(out_path)]
        self._output_dir = self._resolve(output_dir) if output_dir else None

        self.enabled = False
        self.connected = False
        self.error: str | None = None
        self.tools: list[Any] = []  # mcp.types.Tool

        self._session: ClientSession | None = None
        self._task: asyncio.Task | None = None
        self._stop: asyncio.Event | None = None
        self._started: asyncio.Event | None = None

    @staticmethod
    def _resolve(path_value: str) -> Path:
        path = Path(path_value)
        return path if path.is_absolute() else (ROOT_DIR / path)

    @property
    def output_dir(self) -> Path | None:
        return self._output_dir

    def _server_params(self) -> StdioServerParameters:
        command = self.command
        args = list(self.args)
        # На Windows npx — это .cmd; anyio не запускает батники напрямую,
        # поэтому оборачиваем в `cmd /c`.
        if os.name == "nt" and command.lower() in {"npx", "npm", "cmd"}:
            if command.lower() != "cmd":
                args = ["/c", command, *args]
                command = "cmd"
        return StdioServerParameters(command=command, args=args, cwd=str(ROOT_DIR))

    def _visible_tools(self) -> list[Any]:
        if not self._tools_filter:
            return self.tools
        return [tool for tool in self.tools if tool.name in self._tools_filter]

    def tool_names(self) -> list[str]:
        return [f"{self.name}{SEPARATOR}{tool.name}" for tool in self._visible_tools()]

    def openai_tools_schema(self) -> list[dict]:
        if not (self.enabled and self.connected):
            return []
        schema: list[dict] = []
        for tool in self._visible_tools():
            parameters = tool.input_schema or {"type": "object", "properties": {}}
            schema.append(
                {
                    "type": "function",
                    "function": {
                        "name": f"{self.name}{SEPARATOR}{tool.name}",
                        "description": tool.description or self.description,
                        "parameters": parameters,
                    },
                }
            )
        return schema

    def tools_info(self) -> list[dict]:
        if not (self.enabled and self.connected):
            return []
        return [
            {
                "name": f"{self.name}{SEPARATOR}{tool.name}",
                "description": tool.description or self.description,
                "short_description": self.description or None,
                "parameters": tool.input_schema or {"type": "object", "properties": {}},
                "server": self.name,
            }
            for tool in self._visible_tools()
        ]

    async def _serve(self) -> None:
        stop = self._stop or asyncio.Event()
        params = self._server_params()
        try:
            async with stdio_client(params) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    listing = await session.list_tools()
                    self.tools = list(listing.tools)
                    self._session = session
                    self.connected = True
                    self.error = None
                    logger.info("Внешний MCP '%s': подключено, тулов: %s", self.name, len(self.tools))
                    if self._started:
                        self._started.set()
                    await stop.wait()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            logger.warning("Внешний MCP '%s': ошибка: %s", self.name, exc)
        finally:
            self.connected = False
            self._session = None
            if self._started:
                self._started.set()  # чтобы enable() не ждал вечно

    async def enable(self, *, wait: bool = True) -> None:
        if self._task and not self._task.done():
            self.enabled = True
            return
        self.enabled = True
        self.error = None
        self._stop = asyncio.Event()
        self._started = asyncio.Event()
        self._task = asyncio.create_task(self._serve())
        if wait:
            try:
                await asyncio.wait_for(self._started.wait(), timeout=STARTUP_TIMEOUT_SEC)
            except asyncio.TimeoutError:
                logger.warning("Внешний MCP '%s': не успел подключиться за %s сек", self.name, STARTUP_TIMEOUT_SEC)

    async def disable(self) -> None:
        self.enabled = False
        task = self._task
        if self._stop:
            self._stop.set()
        if task and not task.done():
            try:
                await asyncio.wait_for(task, timeout=10)
            except asyncio.TimeoutError:
                task.cancel()
        self._task = None
        self.connected = False
        self._session = None

    def status(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "connected": self.connected,
            "tools_count": len(self._visible_tools()) if self.connected else 0,
            "tools": self.tool_names(),
            "last_error": self.error,
            "output_dir": str(self._output_dir.relative_to(ROOT_DIR)) if self._output_dir else None,
        }


class MCPManager:
    def __init__(self) -> None:
        self._servers: dict[str, ExternalServer] = {}
        self._lock = asyncio.Lock()

    def configure(self, servers: list[dict[str, Any]]) -> None:
        # Вызывается один раз при старте: создаём объекты, читаем сохранённое состояние.
        saved = self._load_state()
        self._servers = {}
        for cfg in servers:
            server = ExternalServer(cfg)
            server.enabled = bool(saved.get(server.name, server.enabled_by_default))
            self._servers[server.name] = server

    def servers(self) -> list[ExternalServer]:
        return list(self._servers.values())

    def enabled_servers(self) -> list[ExternalServer]:
        return [server for server in self._servers.values() if server.enabled]

    async def startup(self) -> None:
        for server in list(self._servers.values()):
            if server.enabled:
                await server.enable(wait=False)

    async def shutdown(self) -> None:
        for server in self._servers.values():
            await server.disable()

    async def set_enabled(self, name: str, enabled: bool) -> dict:
        async with self._lock:
            server = self._servers.get(name)
            if server is None:
                raise KeyError(name)
            if enabled:
                await server.enable(wait=False)
            else:
                await server.disable()
            self._save_state()
            return server.status()

    def status(self) -> list[dict]:
        return [server.status() for server in self._servers.values()]

    def find(self, tool_name: str) -> tuple[ExternalServer, str] | None:
        if SEPARATOR not in tool_name:
            return None
        server_name, real_tool = tool_name.split(SEPARATOR, 1)
        server = self._servers.get(server_name)
        if server is None:
            return None
        visible = [tool for tool in server._visible_tools() if tool.name == real_tool]
        if not visible:
            return None
        return server, real_tool

    def external_tools_schema(self) -> list[dict]:
        schema: list[dict] = []
        for server in self._servers.values():
            schema.extend(server.openai_tools_schema())
        return schema

    def external_tools_info(self) -> list[dict]:
        info: list[dict] = []
        for server in self._servers.values():
            info.extend(server.tools_info())
        return info

    def clear_output_dirs(self) -> int:
        """Очищает содержимое output-папок внешних MCP-серверов (mcp_output).

        Сама папка остаётся — она передана запущенному процессу как --output-dir.
        Возвращает число удалённых объектов.
        """
        removed = 0
        for server in self._servers.values():
            directory = server.output_dir
            if directory is None or not directory.is_dir():
                continue
            for path in sorted(directory.iterdir()):
                try:
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                    removed += 1
                except OSError as exc:
                    logger.warning("Не удалось удалить %s: %s", path, exc)
        return removed

    def screenshot_flow_hint(self) -> str | None:
        """Подсказка промпта про сценарий «саммари + скриншоты» для подключённых серверов."""
        for server in self._servers.values():
            if not (server.enabled and server.connected and server._screenshot_tools):
                continue
            names = [tool.name for tool in server._visible_tools()]
            navigate = next((t for t in names if "navigate" in t.lower()), None)
            shot = next((t for t in names if t in server._screenshot_tools), None)
            if not (navigate and shot):
                continue
            nav_full = f"{server.name}{SEPARATOR}{navigate}"
            shot_full = f"{server.name}{SEPARATOR}{shot}"
            return (
                "Сценарий «саммари со скриншотами»: 1) вызови summarize_best_posts РОВНО ОДИН раз — "
                "он создаёт папку саммари (поле folder) и возвращает список posts с url; "
                "не вызывай summarize_best_posts повторно и не проси статьи через get_saved_articles, "
                f"если URL уже есть в поле posts; 2) для каждого поста из posts: "
                f"сначала {nav_full} (url поста), затем {shot_full} (без параметра filename) — "
                "скриншот автоматически попадёт в папку саммари (поле saved_screenshots в ответе); "
                "3) в финальном ответе укажи путь к папке и имена скриншотов. "
                f"Тулы вида '{server.name}{SEPARATOR}...' принадлежат внешнему MCP-серверу и могут "
                "вызываться последовательно с тулами pikabu в одном диалоге. "
                "Скриншоты можно делать только для разрешённых хостов (pikabu.ru)."
            )
        return None

    def _load_state(self) -> dict[str, bool]:
        try:
            if STATE_FILE.exists():
                return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        return {}

    def _save_state(self) -> None:
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            state = {server.name: server.enabled for server in self._servers.values()}
            STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Не удалось сохранить состояние MCP-серверов: %s", exc)


def _hosts_allowed(arguments: dict, allowed: list[str]) -> bool:
    """Все http(s)-URL в аргументах должны вести на разрешённые хосты (SSRF-политика)."""
    if not allowed:
        return True
    for value in _iter_strings(arguments):
        if not value.startswith(("http://", "https://")):
            continue
        host = (urlparse(value).hostname or "").lower()
        if not any(host == domain or host.endswith("." + domain) for domain in allowed):
            return False
    return True


def _iter_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_strings(item)


manager = MCPManager()


async def call_external(tool_name: str, arguments: dict, summary_dir: Path | None) -> str:
    """Вызов тула внешнего MCP-сервера с маршрутизацией скриншотов в папку саммари."""
    found = manager.find(tool_name)
    if found is None:
        return json.dumps({"error": f"Туал '{tool_name}' недоступен (сервер выключен/не подключён)"}, ensure_ascii=False)
    server, real_tool = found

    allowed = get_settings().allowed_screenshot_hosts
    if not _hosts_allowed(arguments, allowed):
        return json.dumps(
            {"error": f"Разрешены только хосты: {', '.join(allowed)}. Выберите пост с этих сайтов."},
            ensure_ascii=False,
        )

    # Не позволяем модели указать произвольный путь — автосохраняем в output_dir.
    arguments = {k: v for k, v in (arguments or {}).items() if k.lower() not in ("filename", "filepath", "path")}

    session = server._session
    if session is None or not server.connected:
        return json.dumps({"error": f"Сервер '{server.name}' не подключён"}, ensure_ascii=False)

    before = _snapshot(server.output_dir)
    try:
        result = await asyncio.wait_for(session.call_tool(real_tool, arguments), timeout=CALL_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        return json.dumps({"error": f"Таймаут вызова {tool_name}"}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"Ошибка вызова {tool_name}: {exc}"}, ensure_ascii=False)

    saved_files = _collect_screenshots(server, real_tool, before, summary_dir)
    texts = _result_text(result)

    payload: dict[str, Any] = {
        "ok": not getattr(result, "is_error", False),
        "output": texts or "(пустой ответ)",
    }
    if saved_files:
        payload["saved_screenshots"] = saved_files
    if getattr(result, "is_error", False):
        payload["error"] = texts or f"Сервер вернул ошибку для {tool_name}"

    return json.dumps(payload, ensure_ascii=False)


def _snapshot(directory: Path | None) -> set[str]:
    if directory is None or not directory.is_dir():
        return set()
    return {path.name for path in directory.iterdir() if path.is_file()}


def _collect_screenshots(
    server: ExternalServer, real_tool: str, before: set[str], summary_dir: Path | None
) -> list[str]:
    """Перемещает файлы, появившиеся после скриншот-тула, в текущую папку саммари."""
    if real_tool not in server._screenshot_tools:
        return []
    after = _snapshot(server.output_dir)
    new_files = sorted(after - before)
    if not new_files:
        return []

    moved: list[str] = []
    source_dir = server.output_dir
    if source_dir is None:
        return new_files

    if summary_dir is not None:
        summary_dir.mkdir(parents=True, exist_ok=True)
        for filename in new_files:
            src = source_dir / filename
            if not src.is_file():
                continue
            dest = summary_dir / filename
            if dest.exists():
                stem = Path(filename).stem
                suffix = Path(filename).suffix
                dest = summary_dir / f"{stem}_{len(moved)}{suffix}"
            shutil.move(str(src), str(dest))
            moved.append(dest.name)
    return moved or new_files


def _result_text(result) -> str:
    parts: list[str] = []
    for block in getattr(result, "content", []) or []:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            parts.append(block.text)
        elif block_type == "image":
            # base64-картинку в LLM не отдаём (экономия токенов)
            parts.append("[изображение в ответе опущено]")
    return "\n".join(parts).strip()
