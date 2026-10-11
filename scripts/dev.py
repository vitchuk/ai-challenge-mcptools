"""Запуск бэкенда и Vite-клиента в одном терминале (одна команда).

- Бэкенд: `python -m app.main` из `server/` (http://127.0.0.1:8000).
- Клиент: `npm run dev` из `client/` (http://127.0.0.1:5173, проксирует /api и /mcp на :8000).

Вывод обоих процессов идёт в этот терминал с префиксами `[server]` / `[client]`.
Ctrl+C (или завершение одного из процессов) останавливает оба.

Запуск из корня проекта:
    .\\.venv\\Scripts\\python.exe scripts\\dev.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"
CLIENT_DIR = ROOT / "client"


def _enable_utf8_console() -> None:
    """Best-effort: переключает консоль на UTF-8 (иначе кириллица в логах ломается)."""
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:  # noqa: BLE001 — консоли может не быть (перенаправление вывода)
        pass


def _client_command() -> list[str]:
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("npm не найден в PATH. Установите Node.js 18+.")
    # На Windows npm — это npm.cmd: запускаем через cmd /c (надёжнее для subprocess).
    if os.name == "nt":
        return ["cmd", "/c", "npm", "run", "dev"]
    return [npm, "run", "dev"]


def _stream(proc: subprocess.Popen, prefix: str, stop: threading.Event) -> None:
    assert proc.stdout is not None
    for line in proc.stdout:
        if stop.is_set():
            break
        print(f"{prefix} {line.rstrip()}", flush=True)


def _kill(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def main() -> int:
    _enable_utf8_console()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    try:
        client_cmd = _client_command()
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"[server] {sys.executable} -m app.main  (cwd={SERVER_DIR})")
    print(f"[client] {' '.join(client_cmd)}  (cwd={CLIENT_DIR})")
    print("Ctrl+C — остановить оба.\n")

    # Дочерний Python пишет в pipe: без этого он использует кодировку локали (cp1251) и ломает кириллицу.
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"

    common = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,
        "env": env,
    }
    server = subprocess.Popen([sys.executable, "-m", "app.main"], cwd=str(SERVER_DIR), **common)
    client = subprocess.Popen(client_cmd, cwd=str(CLIENT_DIR), **common)

    stop = threading.Event()
    threads = [
        threading.Thread(target=_stream, args=(server, "[server]", stop), daemon=True),
        threading.Thread(target=_stream, args=(client, "[client]", stop), daemon=True),
    ]
    for thread in threads:
        thread.start()

    try:
        while True:
            if server.poll() is not None:
                print(f"\n[server] завершился (код {server.returncode}). Останавливаю клиент.")
                break
            if client.poll() is not None:
                print(f"\n[client] завершился (код {client.returncode}). Останавливаю сервер.")
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nОстановка (Ctrl+C)…")
    finally:
        stop.set()
        _kill(client)
        _kill(server)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
