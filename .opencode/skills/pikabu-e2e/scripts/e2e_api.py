"""E2E smoke-проверка Pikabu MCP-сервера (сам поднимает и останавливает сервер).

Запуск из корня репозитория:
    .venv\\Scripts\\python.exe .opencode\\skills\\pikabu-e2e\\scripts\\e2e_api.py
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PORT = 8000
BASE = f"http://127.0.0.1:{PORT}"
READY_TIMEOUT_SEC = 120
PLAYWRIGHT_TIMEOUT_SEC = 180
EXPECTED_BUILTIN_TOOLS = 28
EXPECTED_TOTAL_TOOLS = 30
EXPECTED_EXTERNAL_TOOLS = {"playwright__browser_navigate", "playwright__browser_take_screenshot"}


def repo_root() -> Path:
    root = Path(__file__).resolve().parents[4]
    if (root / "server" / "app" / "main.py").is_file():
        return root
    for parent in [Path.cwd().resolve(), *Path.cwd().resolve().parents]:
        if (parent / "server" / "app" / "main.py").is_file():
            return parent
    sys.exit("Не найден корень репозитория (server/app/main.py)")


ROOT = repo_root()
SERVER_DIR = ROOT / "server"


def venv_python() -> str:
    for candidate in (ROOT / ".venv" / "Scripts" / "python.exe", ROOT / ".venv" / "bin" / "python"):
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def free_port() -> None:
    if os.name == "nt":
        script = (
            f"Get-NetTCPConnection -LocalPort {PORT} -State Listen -ErrorAction SilentlyContinue | "
            "Select-Object -ExpandProperty OwningProcess -Unique | "
            "ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True)
    else:
        subprocess.run(["bash", "-lc", f"lsof -ti tcp:{PORT} | xargs -r kill"], capture_output=True)


def cleanup_stale_browsers() -> None:
    """Тормозит только осиротевшие headless-Chrome нашего MCP-профиля (ms-playwright), не пользовательский Chrome."""
    try:
        if os.name == "nt":
            script = (
                "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" -ErrorAction SilentlyContinue | "
                "Where-Object { $_.CommandLine -match 'ms-playwright' } | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True)
        else:
            subprocess.run(["bash", "-lc", "pkill -f 'ms-playwright.*mcp-'"], capture_output=True)
    except Exception:  # noqa: BLE001
        pass


def http(method: str, path: str, body: dict | None = None, timeout: int = 120) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "X-Session-Id": "pikabu-e2e"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class Server:
    def __init__(self) -> None:
        self.log = tempfile.NamedTemporaryFile(prefix="pikabu-e2e-", suffix=".log", delete=False)
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        free_port()
        cleanup_stale_browsers()
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
        self.proc = subprocess.Popen(
            [venv_python(), "-m", "app.main"],
            cwd=str(SERVER_DIR),
            env=env,
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )

    def wait_ready(self) -> bool:
        deadline = time.time() + READY_TIMEOUT_SEC
        while time.time() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                return False
            try:
                http("GET", "/api/status", timeout=5)
                return True
            except Exception:  # noqa: BLE001
                time.sleep(2)
        return False

    def wait_playwright(self) -> bool:
        deadline = time.time() + PLAYWRIGHT_TIMEOUT_SEC
        while time.time() < deadline:
            try:
                status = http("GET", "/api/status", timeout=10)
                server = next((s for s in status.get("servers", []) if s["name"] == "playwright"), None)
                if server and server["connected"]:
                    return True
            except Exception:  # noqa: BLE001
                pass
            time.sleep(3)
        return False

    def tail(self, lines: int = 30) -> str:
        try:
            text = Path(self.log.name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "(лог сервера недоступен)"
        informative = [line for line in text.splitlines() if ' - "GET /api/' not in line]
        return "\n".join(informative[-lines:] or text.splitlines()[-lines:])

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        try:
            self.log.close()
        except OSError:
            pass


RESULTS: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok)))
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)
    return bool(ok)


def ensure_playwright(server: "Server") -> bool:
    """Ждёт подключения playwright; если не подключился — один раз перезапускает MCP-сервер."""
    if server.wait_playwright():
        return True
    print("playwright не подключился — перезапускаю MCP-сервер (disable/enable) и жду ещё...", flush=True)
    try:
        http("POST", "/api/mcp-servers/playwright/disable")
        http("POST", "/api/mcp-servers/playwright/enable")
    except Exception as exc:  # noqa: BLE001
        print(f"  не удалось перезапустить playwright: {exc}")
        return False
    return server.wait_playwright()


async def mcp_smoke() -> None:
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except ImportError:
        check("MCP smoke", False, "модуль mcp не найден — запускайте venv-питоном")
        return

    async with streamable_http_client(f"{BASE}/mcp") as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            check("MCP initialize", init.server_info.name == "pikabu-mcp", init.server_info.name)
            tools = await session.list_tools()
            names = [tool.name for tool in tools.tools]
            check("MCP tools/list = 28", len(names) == EXPECTED_BUILTIN_TOOLS, f"{len(names)} тулов")
            result = await session.call_tool("get_saved_articles", {"limit": 2})
            check("MCP call_tool get_saved_articles", not result.is_error)


def main() -> int:
    print(f"Корень репозитория: {ROOT}")
    print(f"Python: {venv_python()}\n")

    server = Server()
    try:
        server.start()
        if not check("Сервер стартовал (GET /api/status)", server.wait_ready()):
            print(server.tail())
            return 1

        status = http("GET", "/api/status")
        check("mcp.connected = true", status["mcp"]["connected"] is True)
        check(
            "mcp.tools_count = 28",
            status["mcp"]["tools_count"] == EXPECTED_BUILTIN_TOOLS,
            str(status["mcp"]["tools_count"]),
        )

        if not check("playwright подключён (первый npx — ~1 мин)", ensure_playwright(server)):
            print(server.tail())

        tools = http("GET", "/api/tools")
        external = {t["name"] for t in tools["tools"] if t.get("server") not in (None, "pikabu")}
        check("GET /api/tools = 30 (28 + 2 playwright)", tools["count"] == EXPECTED_TOTAL_TOOLS, str(tools["count"]))
        check("внешние тулы playwright на месте", external == EXPECTED_EXTERNAL_TOOLS, ", ".join(sorted(external)))

        http("POST", "/api/mcp-servers/playwright/disable")
        tools = http("GET", "/api/tools")
        external = [t["name"] for t in tools["tools"] if t.get("server") == "playwright"]
        check(
            "disable playwright → тулов 28, внешних нет",
            tools["count"] == EXPECTED_BUILTIN_TOOLS and not external,
            str(tools["count"]),
        )

        http("POST", "/api/mcp-servers/playwright/enable")
        if not check("enable playwright → connected", server.wait_playwright()):
            print(server.tail())
        tools = http("GET", "/api/tools")
        check("enable playwright → тулов 30", tools["count"] == EXPECTED_TOTAL_TOOLS, str(tools["count"]))

        articles = http("GET", "/api/articles")
        check("GET /api/articles — count/articles", {"count", "articles"} <= set(articles))

        cleared = http("POST", "/api/parsing/clear-data")
        check(
            "clear-data — поля ответа",
            {"cleared_articles", "cleared_summaries", "cleared_mcp_outputs"} <= set(cleared),
            json.dumps(cleared, ensure_ascii=False),
        )
        check("clear-data → articles_count = 0", http("GET", "/api/status")["articles_count"] == 0)
        check("clear-data → summary/latest.exists = false", http("GET", "/api/summary/latest")["exists"] is False)

        run = http("POST", "/api/parsing/run-now")
        check(
            "run-now → ok, статьи в БД",
            run.get("ok") is True and http("GET", "/api/status")["articles_count"] > 0,
            f"saved={run.get('saved')}, new={run.get('new')}",
        )

        asyncio.run(mcp_smoke())
    except Exception as exc:  # noqa: BLE001
        check(f"непредвиденная ошибка: {exc}", False)
        print(server.tail())
        return 1
    finally:
        server.stop()

    failed = [name for name, ok in RESULTS if not ok]
    print(f"\nИтог: {len(RESULTS) - len(failed)}/{len(RESULTS)} проверок пройдено")
    if failed:
        print("Провалены: " + "; ".join(failed))
        return 1
    print("Все проверки пройдены")
    return 0


if __name__ == "__main__":
    sys.exit(main())
