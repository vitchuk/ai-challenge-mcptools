"""Чат с DeepSeek: диалог + вызовы MCP-тулов (function calling)."""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict, deque

from . import db, deepseek, mcp_manager, rag, tools
from .config import get_settings

logger = logging.getLogger(__name__)

_sessions: dict[str, list[dict]] = defaultdict(list)
_rate_limits: dict[str, deque[float]] = defaultdict(deque)

RESULT_PREVIEW_CHARS = 600

SEPARATOR = mcp_manager.SEPARATOR


def all_tools_schema() -> list[dict]:
    """Схемы тулов для LLM: встроенные + подключённые внешние MCP-серверы."""
    return tools.openai_tools_schema() + mcp_manager.manager.external_tools_schema()


async def route_tool_call(name: str, arguments: dict) -> str:
    """Вызов тула: namespace `server__tool` → внешний сервер, иначе — встроенный реестр."""
    if SEPARATOR in name:
        return await mcp_manager.call_external(name, arguments, tools.current_summary_dir())
    return await tools.call_tool(name, arguments)


def _system_prompt() -> str:
    saved = db.count_articles()
    prompt = (
        "Ты — дружелюбный ассистент веб-клиента Pikabu MCP. Отвечай на русском языке, кратко и по делу. "
        f"В локальной базе сейчас сохранено статей: {saved}.\n"
        "У тебя есть инструменты (tools):\n"
        "- get_saved_articles — статьи, сохранённые в базе (лента /best);\n"
        "- get_theme_<тема> — свежие посты конкретной темы pikabu (например get_theme_humor);\n"
        "- summarize_best_posts — саммари последних N статей из /best; результат сохраняется в папку "
        "(поле folder), туда же автоматически кладутся скриншоты;\n"
        "- save_summary — сохранить результат саммаризации в файл (txt или json);\n"
        "- start_parsing_pikabu / stop_parsing_pikabu — включить/выключить cron-парсинг.\n"
    )

    flow = mcp_manager.manager.screenshot_flow_hint()
    if flow:
        prompt += flow + "\n"

    prompt += (
        "Когда пользователь просит данные с pikabu, содержимое базы, саммари, скриншоты или управление парсингом — "
        "вызывай соответствующие инструменты. Можно вызывать тулы разных MCP-серверов последовательно в одном ответе. "
        "Не выдумывай данные. "
        "Если перечисляешь посты, выводи каждый пост отдельной строкой строго в формате: "
        '"**Заголовок поста** — Автор, рейтинг, комментариев · [ссылка](URL)'
        ' · видео" (часть « · видео» добавляй только если в данных поста есть видео). '
        "Ссылки на посты возвращай как есть. Если инструмент вернул ошибку, сообщи о ней пользователю понятным языком. "
        "Подскажи пользователю, что команда /tools показывает список всех доступных инструментов."
    )
    return prompt


def _check_rate_limit(session_id: str) -> bool:
    settings = get_settings()
    now = time.monotonic()
    bucket = _rate_limits[session_id]
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= settings.chat_rate_limit_per_minute:
        return False
    bucket.append(now)
    return True


def _push_history(session_id: str, message: dict) -> None:
    limit = get_settings().chat_history_limit
    history = _sessions[session_id]
    history.append(message)
    if len(history) > limit:
        del history[: len(history) - limit]


def reset_session(session_id: str) -> None:
    _sessions.pop(session_id, None)


def _assistant_message_payload(message) -> dict:
    payload: dict = {"role": "assistant", "content": message.content or ""}
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.function.name, "arguments": call.function.arguments or "{}"},
            }
            for call in message.tool_calls
        ]
    return payload


def _parse_arguments(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


async def _run_rag_chat(session_id: str, user_message: str, strategy: str) -> dict:
    """Чат в RAG-режиме: чанки выбранной стратегии подмешиваются в вопрос к LLM."""
    try:
        result = await rag.build_rag_reply(user_message, strategy, list(_sessions[session_id]))
    except rag.RagError as exc:
        return {"reply": str(exc), "tool_calls": [], "chunks": [], "error": "rag_error"}
    except deepseek.LLMError as exc:
        return {"reply": str(exc), "tool_calls": [], "chunks": [], "error": "llm_error"}
    except Exception as exc:  # noqa: BLE001 — не роняем сервер из-за ошибок RAG
        logger.warning("Ошибка RAG-чата: %s", exc)
        return {"reply": f"Ошибка RAG-чата: {exc}", "tool_calls": [], "chunks": [], "error": "rag_error"}

    _push_history(session_id, {"role": "user", "content": user_message})
    _push_history(session_id, {"role": "assistant", "content": result["reply"]})
    return {"reply": result["reply"], "tool_calls": [], "chunks": result["chunks"]}


async def run_chat(session_id: str, user_message: str, rag_strategy: str | None = None) -> dict:
    settings = get_settings()
    user_message = (user_message or "").strip()
    rag_strategy = (rag_strategy or "").strip() or None

    if not user_message:
        return {"reply": "Пустое сообщение.", "tool_calls": [], "error": "empty"}
    if len(user_message) > settings.chat_max_message_chars:
        return {
            "reply": f"Сообщение слишком длинное (максимум {settings.chat_max_message_chars} символов).",
            "tool_calls": [],
            "error": "too_long",
        }
    if not _check_rate_limit(session_id):
        return {
            "reply": f"Слишком много сообщений. Лимит — {settings.chat_rate_limit_per_minute} в минуту.",
            "tool_calls": [],
            "error": "rate_limit",
        }
    if not deepseek.is_configured():
        return {
            "reply": (
                "LLM не настроена: добавьте DEEPSEEK_API_KEY в файл .env и перезапустите сервер. "
                "Интерфейс и парсинг при этом работают."
            ),
            "tool_calls": [],
            "error": "llm_not_configured",
        }

    if rag_strategy:
        return await _run_rag_chat(session_id, user_message, rag_strategy)

    client = deepseek.get_client()
    messages: list[dict] = [{"role": "system", "content": _system_prompt()}]
    messages.extend(_sessions[session_id])
    messages.append({"role": "user", "content": user_message})

    tool_events: list[dict] = []
    final_reply = ""
    try:
        for _ in range(max(1, settings.chat_max_iterations)):
            response = await client.chat.completions.create(
                model=settings.deepseek_model,
                messages=messages,
                tools=all_tools_schema(),
                tool_choice="auto",
                temperature=0.7,
                max_tokens=2000,
            )
            message = response.choices[0].message
            if not message.tool_calls:
                final_reply = (message.content or "").strip()
                break

            messages.append(_assistant_message_payload(message))
            for call in message.tool_calls:
                arguments = _parse_arguments(call.function.arguments)
                result = await route_tool_call(call.function.name, arguments)
                tool_events.append(
                    {
                        "name": call.function.name,
                        "arguments": arguments,
                        "result_preview": result[:RESULT_PREVIEW_CHARS],
                        "result": result,
                    }
                )
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
        else:
            final_reply = (
                "Не удалось завершить обработку за отведённое число шагов вызова инструментов. "
                "Попробуйте переформулировать запрос."
            )
    except deepseek.LLMNotConfigured as exc:
        return {"reply": str(exc), "tool_calls": tool_events, "error": "llm_not_configured"}
    except Exception as exc:  # noqa: BLE001 — не роняем сервер из-за ошибок LLM
        logger.warning("Ошибка чата: %s", exc)
        return {"reply": f"Ошибка обращения к LLM: {exc}", "tool_calls": tool_events, "error": "llm_error"}

    final_reply = final_reply or "Модель вернула пустой ответ."
    _push_history(session_id, {"role": "user", "content": user_message})
    _push_history(session_id, {"role": "assistant", "content": final_reply})
    return {"reply": final_reply, "tool_calls": tool_events, "chunks": []}
