"""Память задачи диалога (task state): цель, уточнения пользователя, ограничения/термины.

Структура состояния:
    {
        "goal": str | None,          # формулировка того, чего хочет пользователь
        "clarifications": [str, ...],  # факты, предпочтения, названия, числа
        "constraints": [str, ...],     # правила, определения, форматы, запреты, термины
        "updated_at": str | None,
    }

На каждом ходу состояние обновляется LLM-экстрактором (строгий JSON). При сбое
LLM используется rule-based fallback: прежнее состояние сохраняется, а цель при
необходимости заполняется из первого/текущего сообщения. Состояние хранится
отдельно от окна истории, поэтому не теряется при длинных диалогах.

Модуль не импортирует rag/chat/tools — только deepseek, чтобы не было циклов.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from . import deepseek

logger = logging.getLogger(__name__)

MAX_GOAL_CHARS = 400
MAX_ITEM_CHARS = 220
MAX_ITEMS = 12
_HISTORY_MESSAGES = 6
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)

EXTRACT_SYSTEM_PROMPT = (
    "Ты — экстрактор памяти задачи из диалога. По предыдущему состоянию задачи и новому "
    "сообщению пользователя верни ОБНОВЛЁННОЕ состояние. Поля:\n"
    "- goal — краткая формулировка того, чего пользователь хочет достичь (строка или null);\n"
    "- clarifications — накопленные уточнения пользователя: факты, предпочтения, названия, числа "
    "(массив строк);\n"
    "- constraints — зафиксированные правила, определения, форматы, запреты и термины "
    "(массив строк).\n"
    "Правила: сохраняй прежние пункты, пока они актуальны; добавляй новые; обновляй цель, если "
    "намерение пользователя изменилось; устаревшие пункты убирай. Не выдумывай того, чего "
    "пользователь не говорил. Верни СТРОГО JSON без пояснений и markdown: "
    '{"goal": "...", "clarifications": ["..."], "constraints": ["..."]}'
)


def empty_state() -> dict:
    return {"goal": None, "clarifications": [], "constraints": [], "updated_at": None}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_text(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:limit]


def _clean_list(value: object, limit: int = MAX_ITEMS) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _clean_text(item, MAX_ITEM_CHARS)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def normalize_state(raw: dict | None) -> dict:
    """Приводит произвольный словарь к канонической структуре состояния."""
    raw = raw if isinstance(raw, dict) else {}
    goal = raw.get("goal")
    goal = _clean_text(goal, MAX_GOAL_CHARS) if goal else None
    return {
        "goal": goal or None,
        "clarifications": _clean_list(raw.get("clarifications")),
        "constraints": _clean_list(raw.get("constraints")),
        "updated_at": raw.get("updated_at") or None,
    }


def _parse_state(raw: str) -> dict | None:
    """Извлекает JSON-объект из ответа LLM; None — если распарсить не удалось."""
    match = _JSON_OBJECT_RE.search(raw or "")
    payload = match.group(0) if match else (raw or "")
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    if not any(key in data for key in ("goal", "clarifications", "constraints")):
        return None
    return normalize_state(data)


def _fallback_state(user_message: str, current: dict | None) -> dict:
    """Rule-based fallback: сохраняем прежнее состояние, при отсутствии цели — сеем из сообщения."""
    state = normalize_state(current) if current else empty_state()
    if not state["goal"] and user_message.strip():
        state["goal"] = _clean_text(user_message, MAX_GOAL_CHARS)
    return state


def _format_history(history: list[dict] | None) -> str:
    lines: list[str] = []
    for message in list(history or [])[-_HISTORY_MESSAGES:]:
        role = message.get("role")
        content = _clean_text(message.get("content"), 300)
        if role not in ("user", "assistant") or not content:
            continue
        label = "Пользователь" if role == "user" else "Ассистент"
        lines.append(f"{label}: {content}")
    return "\n".join(lines)


async def update_state(
    user_message: str,
    history: list[dict] | None,
    current: dict | None,
) -> dict:
    """Обновляет память задачи на основе нового сообщения и накопленного состояния.

    Ошибки LLM не пробрасываются: при сбое возвращается rule-based fallback.
    """
    previous = normalize_state(current) if current else empty_state()
    prompt_parts: list[str] = [
        "Текущее состояние задачи (JSON):",
        json.dumps(
            {
                "goal": previous["goal"],
                "clarifications": previous["clarifications"],
                "constraints": previous["constraints"],
            },
            ensure_ascii=False,
        ),
    ]
    history_text = _format_history(history)
    if history_text:
        prompt_parts.append("\nПоследние сообщения диалога:\n" + history_text)
    prompt_parts.append(f"\nНовое сообщение пользователя: {user_message}")
    prompt_parts.append("\nОбновлённое состояние задачи (JSON):")
    prompt = "\n".join(prompt_parts)

    try:
        raw = await deepseek.complete_text(
            EXTRACT_SYSTEM_PROMPT, prompt, temperature=0.0, max_tokens=700
        )
    except deepseek.LLMError as exc:
        logger.warning("Экстрактор памяти задачи недоступен, fallback: %s", exc)
        return _fallback_state(user_message, previous)

    parsed = _parse_state(raw)
    if parsed is None:
        logger.warning("Экстрактор памяти задачи вернул не JSON: %s", (raw or "")[:120])
        return _fallback_state(user_message, previous)

    if parsed["goal"] is None and previous["goal"]:
        parsed["goal"] = previous["goal"]
    parsed["updated_at"] = _now_iso()
    return parsed


def format_for_prompt(state: dict | None) -> str:
    """Текстовый блок состояния задачи для подмешивания в промпты (генерация/rewrite)."""
    data = normalize_state(state) if state else empty_state()
    if not data["goal"] and not data["clarifications"] and not data["constraints"]:
        return ""
    lines = ["Состояние задачи (память диалога):"]
    if data["goal"]:
        lines.append(f"Цель: {data['goal']}")
    if data["clarifications"]:
        lines.append("Уточнения пользователя:")
        lines.extend(f"- {item}" for item in data["clarifications"])
    if data["constraints"]:
        lines.append("Ограничения, термины и правила:")
        lines.extend(f"- {item}" for item in data["constraints"])
    return "\n".join(lines)
