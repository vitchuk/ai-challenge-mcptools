"""Проверка влияния параметров генерации (temperature / top_p / top_k) на ответы LLM.

Гоняет 10 контрольных вопросов (`scripts/sampling_questions.json`) по обоим провайдерам
в конфигурациях:
  A — детерминизм: temperature=0            -> повторы должны совпадать;
  B — креатив:     temperature=1.5, top_p=.95 -> повторы должны различаться;
  C — контроль:    temperature=1.5, top_p=.1, top_k=1 -> повторы снова совпадают
                   (DeepSeek применяет top_p, Ollama — top_k).

Плюс блок «экономия токенов»: прямой вызов Ollama с think=true/false и замер eval_count.

Скрипт сам поднимает и останавливает сервер. Результаты:
`docs/scenarios/sampling-check.md` и `docs/scenarios/sampling-check.json`.

Запуск (из корня проекта):
    .\\.venv\\Scripts\\python.exe scripts\\run_sampling_checks.py
"""

from __future__ import annotations

import difflib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE_URL = "http://127.0.0.1:8000"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_ROOT / "server"
DOCS_DIR = PROJECT_ROOT / "docs" / "scenarios"
QUESTIONS_PATH = PROJECT_ROOT / "scripts" / "sampling_questions.json"
SERVER_LOG = SERVER_DIR / "data" / "sampling_server.log"
REQUEST_TIMEOUT = 300.0
RUNS = 2

CONFIGS: list[dict] = [
    {
        "id": "A_deterministic",
        "title": "A. Детерминизм (temperature=0)",
        "expect": "высокая похожесть повторов",
        "sampling": {"temperature": 0.0, "top_p": 1.0, "no_think": True},
    },
    {
        "id": "B_creative",
        "title": "B. Креатив (temperature=1.5, top_p=0.95)",
        "expect": "низкая похожесть (ответы различаются)",
        "sampling": {"temperature": 1.5, "top_p": 0.95, "no_think": True},
    },
    {
        "id": "C_control",
        "title": "C. Контроль параметра (t=1.5, top_p=0.01, top_k=1)",
        "expect": "похожесть выше, чем в B (top_p у DeepSeek, top_k у Ollama)",
        "sampling": {"temperature": 1.5, "top_p": 0.01, "top_k": 1, "no_think": True},
    },
]

REPLY_CAP = 1500

TOKEN_PROBES = [1, 3, 7]


def request(client: httpx.Client, method: str, path: str, *, payload: dict | None = None) -> dict:
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = client.request(method, f"{BASE_URL}{path}", json=payload)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(3)
    raise RuntimeError(f"{method} {path} не удался: {last_error}")


def start_server() -> subprocess.Popen:
    SERVER_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = open(SERVER_LOG, "w", encoding="utf-8")  # noqa: SIM115
    print(f"Запускаю сервер: {sys.executable} -m app.main (cwd={SERVER_DIR})")
    return subprocess.Popen(
        [sys.executable, "-m", "app.main"],
        cwd=str(SERVER_DIR),
        stdout=log,
        stderr=subprocess.STDOUT,
    )


def wait_for_server(client: httpx.Client, timeout: float = 180.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if client.get(f"{BASE_URL}/api/status", timeout=5).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(2)
    return False


def stop_server(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def run_config(
    client: httpx.Client,
    provider: str,
    config: dict,
    questions: list[dict],
    created: list[str],
) -> dict:
    results: list[dict] = []
    for question in questions:
        replies: list[str] = []
        elapsed: list[float] = []
        reasoning: list[bool] = []
        for run in range(RUNS):
            session_id = f"sampling-{provider}-{config['id']}-{question['id']}-{run}"
            created.append(session_id)
            data = request(
                client,
                "POST",
                "/api/chat",
                payload={
                    "message": question["text"],
                    "session_id": session_id,
                    "llm_provider": provider,
                    "sampling": config["sampling"],
                },
            )
            replies.append((data.get("reply") or "").strip())
            elapsed.append(float(data.get("elapsed_ms") or 0))
            reasoning.append(bool(data.get("reasoning")))
        pairs = [similarity(replies[i], replies[j]) for i in range(len(replies)) for j in range(i + 1, len(replies))]
        results.append(
            {
                "id": question["id"],
                "text": question["text"],
                "replies": [reply[:REPLY_CAP] for reply in replies],
                "identical": len(set(replies)) == 1,
                "similarity": round(sum(pairs) / len(pairs), 3) if pairs else 1.0,
                "elapsed_ms": round(sum(elapsed) / len(elapsed), 1),
                "reasoning": any(reasoning),
            }
        )
    identical = sum(1 for item in results if item["identical"])
    similar = sum(1 for item in results if item["similarity"] >= 0.9)
    avg_similarity = round(sum(item["similarity"] for item in results) / len(results), 3)
    return {
        "config": config["id"],
        "title": config["title"],
        "expect": config["expect"],
        "questions": results,
        "identical": identical,
        "similar": similar,
        "total": len(results),
        "avg_similarity": avg_similarity,
    }


def measure_tokens(client: httpx.Client, ollama_base: str, model: str, question: str, no_think: bool) -> dict:
    payload: dict = {
        "model": model,
        "messages": [{"role": "user", "content": question}],
        "stream": False,
        "options": {"num_predict": 1000},
    }
    if no_think:
        payload["think"] = False
    response = httpx.post(f"{ollama_base}/api/chat", json=payload, timeout=300.0)
    response.raise_for_status()
    data = response.json()
    return {
        "eval_count": data.get("eval_count"),
        "prompt_eval_count": data.get("prompt_eval_count"),
        "reply_chars": len((data.get("message") or {}).get("content") or ""),
    }


def write_report(payload: dict) -> tuple[Path, Path]:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = DOCS_DIR / "sampling-check.json"
    md_path = DOCS_DIR / "sampling-check.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines: list[str] = [
        "# Проверка параметров генерации LLM",
        "",
        f"Дата: {payload['created_at']}",
        "",
        "## Сводка по конфигурациям",
        "",
        "| Провайдер | Конфигурация | Ср. похожесть | Совпало | Похожих (≥0.9) | Всего | Ожидание |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for provider in payload["providers"]:
        for cfg in provider["configs"]:
            lines.append(
                f"| {provider['provider']} | {cfg['title']} | {cfg['avg_similarity']} | "
                f"{cfg['identical']} | {cfg['similar']} | {cfg['total']} | {cfg['expect']} |"
            )
    lines.append("")
    lines.append("## Ответы по вопросам")
    for provider in payload["providers"]:
        lines.append("")
        lines.append(f"### {provider['provider']}")
        for cfg in provider["configs"]:
            lines.append("")
            lines.append(f"**{cfg['title']}** — ср. похожесть {cfg['avg_similarity']}, "
                         f"совпало {cfg['identical']}/{cfg['total']}, похожих {cfg['similar']}/{cfg['total']}")
            for item in cfg["questions"]:
                mark = "= одинаково" if item["identical"] else f"≠ (sim {item['similarity']})"
                lines.append(f"- Q{item['id']} [{mark}], ⏱ {item['elapsed_ms']} мс:")
                for idx, reply in enumerate(item["replies"], start=1):
                    lines.append(f"    - {idx}: {reply}")
    if payload.get("token_savings"):
        lines.append("")
        lines.append("## Экономия токенов (Ollama, eval_count)")
        lines.append("")
        lines.append("| Вопрос | think=true | think=false | Экономия |")
        lines.append("| --- | --- | --- | --- |")
        for item in payload["token_savings"]:
            lines.append(
                f"| Q{item['id']} | {item['with_think']} | {item['without_think']} | {item['saved']} токенов |"
            )
        lines.append("")
        lines.append(f"Итого: {payload['token_savings_total']['with_think']} → "
                     f"{payload['token_savings_total']['without_think']} токенов "
                     f"({payload['token_savings_total']['saved']} экономии).")
    if payload.get("test_chats_deleted") is not None:
        lines.append("")
        lines.append(f"Тестовых чатов удалено после прогона: {payload['test_chats_deleted']}.")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path, json_path


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))["questions"]
    print(f"Вопросов: {len(questions)}; конфигураций: {len(CONFIGS)}; повторов: {RUNS}")

    server_proc: subprocess.Popen | None = None
    report: dict = {"created_at": datetime.now(timezone.utc).isoformat(), "providers": []}
    created_sessions: list[str] = []
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            try:
                status = request(client, "GET", "/api/status")
            except RuntimeError:
                server_proc = start_server()
                if not wait_for_server(client):
                    print(f"Не удалось дождаться сервера. Лог: {SERVER_LOG}", file=sys.stderr)
                    return 1
                status = request(client, "GET", "/api/status")

            llm = status.get("llm") or {}
            deepseek_ok = bool((llm.get("deepseek") or {}).get("configured"))
            ollama = llm.get("ollama") or {}
            ollama_ok = bool(ollama.get("available"))

            providers: list[str] = []
            if deepseek_ok:
                providers.append("deepseek")
            if ollama_ok:
                providers.append("ollama")
            if not providers:
                print("Нет доступных провайдеров (DeepSeek ключ / Ollama).", file=sys.stderr)
                return 1
            print(f"Провайдеры: {', '.join(providers)}")

            for provider in providers:
                provider_result = {"provider": provider, "configs": []}
                for config in CONFIGS:
                    print(f"  {provider} / {config['id']} …")
                    provider_result["configs"].append(
                        run_config(client, provider, config, questions, created_sessions)
                    )
                report["providers"].append(provider_result)

            if ollama_ok:
                base = ollama.get("base_url") or "http://127.0.0.1:11434"
                model = ollama.get("model") or "qwen3:1.7b"
                print("  экономия токенов (Ollama think on/off) …")
                savings: list[dict] = []
                with_think_total = 0
                without_think_total = 0
                for question in questions:
                    if question["id"] not in TOKEN_PROBES:
                        continue
                    on = measure_tokens(client, base, model, question["text"], no_think=False)
                    off = measure_tokens(client, base, model, question["text"], no_think=True)
                    w = int(on["eval_count"] or 0)
                    wo = int(off["eval_count"] or 0)
                    with_think_total += w
                    without_think_total += wo
                    savings.append(
                        {"id": question["id"], "with_think": w, "without_think": wo, "saved": w - wo}
                    )
                report["token_savings"] = savings
                report["token_savings_total"] = {
                    "with_think": with_think_total,
                    "without_think": without_think_total,
                    "saved": with_think_total - without_think_total,
                }

            # чистим созданные для теста чаты (пользовательские не трогаем)
            deleted = 0
            for session_id in created_sessions:
                try:
                    request(client, "POST", f"/api/chats/{session_id}/delete")
                    deleted += 1
                except RuntimeError:
                    pass
            report["test_chats_deleted"] = deleted
            print(f"  удалено тестовых чатов: {deleted}/{len(created_sessions)}")
    finally:
        stop_server(server_proc)

    md_path, json_path = write_report(report)

    print("\n================ СВОДКА ================")
    for provider in report["providers"]:
        for cfg in provider["configs"]:
            print(
                f"{provider['provider']:8} {cfg['config']:16} ср.похожесть {cfg['avg_similarity']:.3f}, "
                f"совпало {cfg['identical']}/{cfg['total']}, похожих {cfg['similar']}/{cfg['total']}"
            )
    if report.get("token_savings_total"):
        total = report["token_savings_total"]
        print(f"Токены Ollama: {total['with_think']} (think) -> {total['without_think']} (no_think), "
              f"экономия {total['saved']}")
    print("=======================================")
    print(f"Отчёт: {md_path.relative_to(PROJECT_ROOT)} и {json_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
