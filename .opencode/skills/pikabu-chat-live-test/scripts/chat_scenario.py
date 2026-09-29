"""Живой тест чат-агента Pikabu MCP: «саммари N постов + скриншоты».

Запуск из корня репозитория:
    .venv\\Scripts\\python.exe .opencode\\skills\\pikabu-chat-live-test\\scripts\\chat_scenario.py
"""

from __future__ import annotations

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
CHAT_TIMEOUT_SEC = 300
MESSAGE = "Сделай саммари 2 последних постов и их скриншоты"
EXPECTED_SHOTS = 2


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
SUMMARIES_DIR = SERVER_DIR / "data" / "summaries"


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
        headers={"Content-Type": "application/json", "X-Session-Id": "pikabu-chat-live-test"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def deepseek_key_present() -> bool:
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return False
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith("DEEPSEEK_API_KEY="):
            return bool(line.split("=", 1)[1].strip())
    return False


class Server:
    def __init__(self) -> None:
        self.log = tempfile.NamedTemporaryFile(prefix="pikabu-chat-test-", suffix=".log", delete=False)
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


def scenario() -> int:
    server = Server()
    try:
        server.start()
        if not check("Сервер стартовал", server.wait_ready()):
            print(server.tail())
            return 1
        if not check("playwright подключён", ensure_playwright(server)):
            print(server.tail())
            return 1

        if not deepseek_key_present():
            print("\nSKIP: DEEPSEEK_API_KEY не задан в .env — живой чат-сценарий пропущен "
                  "(сервер и playwright подключены).")
            return 0

        http("POST", "/api/parsing/clear-data")
        run = http("POST", "/api/parsing/run-now")
        check("run-now заполнил БД", run.get("ok") is True and http("GET", "/api/status")["articles_count"] > 0,
              f"saved={run.get('saved')}")

        started = time.time()
        reply = http("POST", "/api/chat", {"message": MESSAGE, "session_id": "pikabu-chat-live-test"},
                     timeout=CHAT_TIMEOUT_SEC)
        elapsed = time.time() - started
        names = [call["name"] for call in reply.get("tool_calls", [])]
        print(f"Чат ответил за {elapsed:.0f} с; тулы: {names}")
        print("Ответ (начало): " + (reply.get("reply") or "").replace("\n", " ")[:300])

        check("ответ непустой, без ошибки", bool(reply.get("reply")) and not reply.get("error"))
        check("вызван summarize_best_posts", "summarize_best_posts" in names)
        check("вызван playwright__browser_take_screenshot",
              "playwright__browser_take_screenshot" in names)

        folders = sorted(p for p in SUMMARIES_DIR.glob("summary_*") if p.is_dir()) if SUMMARIES_DIR.is_dir() else []
        check("ровно одна папка саммари", len(folders) == 1,
              f"{len(folders)}: {', '.join(p.name for p in folders)}")

        if len(folders) == 1:
            folder = folders[0]
            files = [p.name for p in folder.iterdir()]
            pngs = [name for name in files if name.lower().endswith(".png")]
            check("в папке summary.json", "summary.json" in files, ", ".join(files))
            check(f"PNG-скриншоты (ожидается {EXPECTED_SHOTS})", len(pngs) >= 1, f"{len(pngs)} шт.")

        flats = sorted(p.name for p in SUMMARIES_DIR.glob("*.json")) if SUMMARIES_DIR.is_dir() else []
        check("плоские файлы — только summary_auto_*.json",
              bool(flats) and all(name.startswith("summary_auto_") for name in flats), ", ".join(flats))

        latest = http("GET", "/api/summary/latest")
        check("summary/latest указывает на папку", bool(latest.get("folder")), str(latest.get("folder")))
        check("last_summary_error пуст", http("GET", "/api/status")["parsing"]["last_summary_error"] is None)
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
    sys.exit(scenario())
