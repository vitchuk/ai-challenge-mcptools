"""Прогон двух длинных сценариев RAG-чата с памятью задачи и выводом источников.

Предусловия:
- сервер поднят на http://127.0.0.1:8000;
- собран RAG-индекс: `..\\.venv\\Scripts\\python.exe -m app.rag build` (из папки server);
- в .env задан DEEPSEEK_API_KEY.

Запуск (из корня проекта):
    .\\.venv\\Scripts\\python.exe scripts\\run_chat_scenarios.py

Скрипт сбрасывает сессии `scenario-1`/`scenario-2`, прогоняет по 13 сообщений
(уточнения, смена условий, новые термины/запреты, вопросы с возвратом к ранее
сказанному), сохраняет транскрипты в docs/scenarios/ и печатает сводку проверок:
источники в каждом ответе, сохранение цели, накопление уточнений/ограничений,
а также отдельный probe «нет релевантных источников».
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

import httpx

BASE_URL = "http://127.0.0.1:8000"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_ROOT / "server"
DOCS_DIR = PROJECT_ROOT / "docs" / "scenarios"
SERVER_LOG = SERVER_DIR / "data" / "scenario_server.log"
RAG_STRATEGY = "fixed"
RAG_OPTIONS = {
    "strategy": "query-rewrite-rerank",
    "top_k_before": 12,
    "top_k_final": 5,
}
NO_SOURCES_OPTIONS = {
    "strategy": "similarity-filter",
    "top_k_before": 10,
    "similarity_threshold": 0.99,
}
REQUEST_TIMEOUT = 240.0

SCENARIOS: list[dict] = [
    {
        "id": "scenario-1",
        "title": "Материалы для школьного научного вечера о космосе",
        "goal_hint": "подготовить материал о космосе для научного вечера 7–8 классов",
        "messages": [
            "Привет! Помоги подготовить материал для школьного научного вечера о космосе.",
            "Дай простые факты о том, как Земля вращается вокруг Солнца.",
            "Учти: аудитория — ученики 7–8 классов, поэтому объясняй без формул и сложных терминов.",
            "Что говорится про наклон земной оси и смену сезонов?",
            "Добавь ограничение: все факты только из статей базы, ничего не придумывай.",
            "А почему Земля не падает на Солнце?",
            "Теперь сменим условие: оставь только 3 самых ярких факта, коротко.",
            "Запомни термин: под «орбитальной скоростью» я понимаю скорость движения Земли по орбите вокруг Солнца.",
            "Какая орбитальная скорость Земли в перигелии и афелии?",
            "Вернись к самому первому вопросу: какова была тема нашего научного вечера?",
            "Правда ли, что звёздные сутки короче солнечных?",
            "И напомни, какое ограничение по аудитории мы установили в начале диалога.",
            "Отлично. Сформулируй итоговую цель нашего диалога одним предложением.",
        ],
    },
    {
        "id": "scenario-2",
        "title": "Квиз (викторина) по базе научных статей",
        "goal_hint": "составить викторину из вопросов по базе научных статей",
        "messages": [
            "Хочу сделать викторину из 5 вопросов по нашей базе научных статей.",
            "Первый вопрос пусть будет про феномен третьего человека — что это такое?",
            "Уточнение: вопросы должны быть с вариантами ответов — 4 варианта и один верный.",
            "Введи термин: «факт-вопрос» — это вопрос, ответ на который дословно есть в статье.",
            "Сделай факт-вопрос про парадоксальное раздевание на морозе.",
            "Запрет: не используй в викторине вопросы про животных и собак.",
            "Теперь вопрос про эффект Джанибекова — в чём его суть?",
            "Вернись к термину «факт-вопрос»: соответствует ли ему вопрос про эффект Джанибекова?",
            "Добавь вопрос про холодильник для семян: зачем каштанчикам зима?",
            "Сколько вопросов у нас уже есть и каких типов?",
            "Напомни ограничения, которые мы вводили по ходу диалога.",
            "Сменим условие: сократи викторину до 3 факт-вопросов.",
            "А теперь проверь: не нарушают ли выбранные вопросы запрет про животных?",
        ],
    },
]

NO_SOURCES_PROBE = {
    "session_id": "probe-no-sources",
    "message": "Как приготовить классический борщ со свёклой и капустой?",
}


def request_with_retry(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    payload: dict | None = None,
) -> dict:
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


def reset_session(client: httpx.Client, session_id: str) -> None:
    request_with_retry(client, "POST", "/api/chat/reset", payload={"session_id": session_id})


def send_message(client: httpx.Client, session_id: str, message: str, options: dict) -> dict:
    return request_with_retry(
        client,
        "POST",
        "/api/chat",
        payload={
            "message": message,
            "session_id": session_id,
            "rag_strategy": RAG_STRATEGY,
            "rag_options": options,
        },
    )


def sources_lines(chunks: Iterable[dict]) -> list[str]:
    lines: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        metadata = chunk.get("metadata") or {}
        title = metadata.get("title") or "Без названия"
        url = metadata.get("url") or ""
        score = chunk.get("score")
        lines.append(f"{index}. `{chunk.get('id')}` — {title} ({url}) · similarity {score}")
    return lines


def state_block(state: dict | None) -> str:
    if not state:
        return "_Память задачи пока пуста._"
    lines: list[str] = []
    lines.append(f"**Цель:** {state.get('goal') or '—'}")
    clarifications = state.get("clarifications") or []
    constraints = state.get("constraints") or []
    lines.append(f"**Уточнения:** {'; '.join(clarifications) if clarifications else '—'}")
    lines.append(f"**Ограничения и термины:** {'; '.join(constraints) if constraints else '—'}")
    return "  \n".join(lines)


def turn_check(turn: dict) -> str:
    reply = turn["response"].get("reply") or ""
    chunks = turn["response"].get("chunks") or []
    has_sources = bool(chunks) or "Источники:" in reply
    return "OK" if has_sources else "FAIL"


def run_scenario(client: httpx.Client, scenario: dict) -> list[dict]:
    session_id = scenario["id"]
    reset_session(client, session_id)
    print(f"\n=== {scenario['id']}: {scenario['title']} ===")
    turns: list[dict] = []
    for index, message in enumerate(scenario["messages"], start=1):
        started = time.monotonic()
        response = send_message(client, session_id, message, RAG_OPTIONS)
        elapsed = time.monotonic() - started
        turn = {"index": index, "message": message, "response": response, "elapsed": elapsed}
        turns.append(turn)
        chunks = response.get("chunks") or []
        state = response.get("task_state") or {}
        print(
            f"  [{index:02d}/{len(scenario['messages'])}] источников: {len(chunks)} "
            f"· цель: {(state.get('goal') or '—')[:60]!r} · {elapsed:.1f}s {turn_check(turn)}"
        )
    return turns


def write_transcript(scenario: dict, turns: list[dict], checks: dict) -> Path:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    path = DOCS_DIR / f"{scenario['id']}.md"
    lines: list[str] = [
        f"# Проверочный сценарий: {scenario['title']}",
        "",
        f"- Сессия: `{scenario['id']}`",
        f"- Режим: RAG-индекс `{RAG_STRATEGY}`, поиск `{RAG_OPTIONS['strategy']}` "
        f"(top_k_before={RAG_OPTIONS['top_k_before']}, top_k_final={RAG_OPTIONS['top_k_final']})",
        f"- Дата прогона: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- Сообщений: {len(scenario['messages'])}",
        "",
        "## Итоговые проверки",
        "",
        f"- Источники в каждом ответе: {'✅ да' if checks['sources_ok'] else '❌ нет'} "
        f"({checks['sources_ok_count']}/{checks['turns']})",
        f"- Цель диалога сохранена: {'✅ да' if checks['goal_ok'] else '❌ нет'} "
        f"(итог: {checks['final_goal']!r})",
        f"- Накоплено уточнений/ограничений: {checks['state_items']} "
        f"(уточнений {checks['clarifications']}, ограничений {checks['constraints']})",
        "",
        "## Диалог",
        "",
    ]
    for turn in turns:
        response = turn["response"]
        lines.append(f"### {turn['index']}. Пользователь")
        lines.append("")
        lines.append(f"> {turn['message']}")
        lines.append("")
        lines.append(f"**Ассистент** ({turn['elapsed']:.1f}s, источников "
                     f"{len(response.get('chunks') or [])}):")
        lines.append("")
        lines.append(response.get("reply") or "_пустой ответ_")
        lines.append("")
        sources = sources_lines(response.get("chunks") or [])
        lines.append("**Найденные источники:**")
        lines.append("")
        if sources:
            lines.extend(sources)
        else:
            lines.append("_Релевантные фрагменты не найдены._")
        lines.append("")
        lines.append("**Память задачи после хода:**")
        lines.append("")
        lines.append(state_block(response.get("task_state")))
        debug = response.get("debug")
        if debug:
            counts = debug.get("counts") or {}
            lines.append("")
            lines.append(
                f"<sub>retrieval: {debug.get('retrieval_strategy')} · "
                f"rewritten: {debug.get('rewritten_query')!r} · "
                f"counts: vector {counts.get('retrieved')} → similarity "
                f"{counts.get('after_similarity_filter')} → reranker "
                f"{counts.get('after_reranker_filter')} → final {counts.get('final')}</sub>"
            )
        lines.append("")
        lines.append("---")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def evaluate(scenario: dict, turns: list[dict]) -> dict:
    sources_ok_count = sum(
        1
        for turn in turns
        if (turn["response"].get("chunks") or []) or "Источники:" in (turn["response"].get("reply") or "")
    )
    final_state = turns[-1]["response"].get("task_state") or {}
    clarifications = final_state.get("clarifications") or []
    constraints = final_state.get("constraints") or []
    return {
        "turns": len(turns),
        "sources_ok": sources_ok_count == len(turns),
        "sources_ok_count": sources_ok_count,
        "goal_ok": bool(final_state.get("goal")),
        "final_goal": final_state.get("goal"),
        "clarifications": len(clarifications),
        "constraints": len(constraints),
        "state_items": len(clarifications) + len(constraints),
    }


def run_no_sources_probe(client: httpx.Client) -> dict:
    session_id = NO_SOURCES_PROBE["session_id"]
    reset_session(client, session_id)
    print(f"\n=== probe: нет релевантных источников ({session_id}) ===")
    response = send_message(client, session_id, NO_SOURCES_PROBE["message"], NO_SOURCES_OPTIONS)
    reply = response.get("reply") or ""
    chunks = response.get("chunks") or []
    ok = not chunks and "не найдены" in reply
    print(f"  источников: {len(chunks)} · сообщение об отсутствии: {'OK' if ok else 'FAIL'}")
    return {
        "message": NO_SOURCES_PROBE["message"],
        "reply": reply,
        "chunks": chunks,
        "debug": response.get("debug"),
        "ok": ok,
    }


def write_probe(probe: dict) -> Path:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    path = DOCS_DIR / "probe-no-sources.md"
    lines = [
        "# Probe: вопрос без релевантных источников",
        "",
        f"- Режим: RAG-индекс `{RAG_STRATEGY}`, поиск `{NO_SOURCES_OPTIONS['strategy']}` "
        f"(similarity_threshold={NO_SOURCES_OPTIONS['similarity_threshold']})",
        f"- Результат: {'✅ сообщение об отсутствии источников выведено' if probe['ok'] else '❌'}",
        "",
        "### Пользователь",
        "",
        f"> {probe['message']}",
        "",
        "### Ассистент",
        "",
        probe["reply"],
        "",
        f"**Найденные источники:** {len(probe['chunks'])}",
        "",
    ]
    debug = probe.get("debug")
    if debug:
        lines.append(f"<sub>debug: {json.dumps(debug, ensure_ascii=False)}</sub>")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def start_server() -> subprocess.Popen:
    """Запускает сервер (python -m app.main) в фоне; логи — server/data/scenario_server.log."""
    SERVER_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = open(SERVER_LOG, "w", encoding="utf-8")  # noqa: SIM115 — держим открытым до остановки
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
            response = client.get(f"{BASE_URL}/api/status", timeout=5)
            if response.status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(2)
    return False


def stop_server(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def main() -> int:
    print(f"Сервер: {BASE_URL}; транскрипты: {DOCS_DIR}")
    server_proc: subprocess.Popen | None = None
    with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
        try:
            status = request_with_retry(client, "GET", "/api/status")
        except RuntimeError:
            server_proc = start_server()
            if not wait_for_server(client):
                print(
                    f"Не удалось дождаться сервера. Лог: {SERVER_LOG}",
                    file=sys.stderr,
                )
                stop_server(server_proc)
                return 1
            status = request_with_retry(client, "GET", "/api/status")
        if not (status.get("llm") or {}).get("configured"):
            print("DEEPSEEK_API_KEY не настроен — живой чат невозможен.", file=sys.stderr)
            stop_server(server_proc)
            return 1

        try:
            results: list[tuple[str, dict, list[dict], Path]] = []
            for scenario in SCENARIOS:
                turns = run_scenario(client, scenario)
                checks = evaluate(scenario, turns)
                path = write_transcript(scenario, turns, checks)
                results.append((scenario["id"], checks, turns, path))

            probe = run_no_sources_probe(client)
            probe_path = write_probe(probe)
        finally:
            stop_server(server_proc)

    print("\n================ СВОДКА ================")
    all_ok = True
    for scenario_id, checks, _, path in results:
        ok = checks["sources_ok"] and checks["goal_ok"] and checks["state_items"] > 0
        all_ok = all_ok and ok
        print(
            f"{'OK' if ok else 'FAIL'} {scenario_id}: источники {checks['sources_ok_count']}/"
            f"{checks['turns']}, цель {'есть' if checks['goal_ok'] else 'НЕТ'}, "
            f"уточнений/ограничений {checks['state_items']} -> {path.relative_to(PROJECT_ROOT)}"
        )
    print(f"{'OK' if probe['ok'] else 'FAIL'} probe-no-sources -> {probe_path.relative_to(PROJECT_ROOT)}")
    all_ok = all_ok and probe["ok"]
    print("=======================================")
    print("ИТОГ:", "ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ" if all_ok else "ЕСТЬ ЗАМЕЧАНИЯ")
    return 0 if all_ok else 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
