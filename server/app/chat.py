"""Чат с LLM (DeepSeek / локальный Ollama): диалог + вызовы MCP-тулов (function calling)."""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict, deque

from . import chat_store, db, llm, mcp_manager, rag, rag_pipeline, task_state, tools
from .config import get_settings

logger = logging.getLogger(__name__)

_rate_limits: dict[str, deque[float]] = defaultdict(deque)

RESULT_PREVIEW_CHARS = 600

SEPARATOR = mcp_manager.SEPARATOR


def _elapsed_ms(started: float | None) -> float | None:
    """Время обработки в мс от `started` (time.monotonic) или None."""
    if started is None:
        return None
    return round((time.monotonic() - started) * 1000, 1)


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
        "Ты — дружелюбный ассистент веб-клиента Ai Playground. Отвечай на русском языке, кратко и по делу. "
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


def _load_history(session_id: str) -> list[dict]:
    """История диалога из SQLite (последние chat_history_limit сообщений)."""
    return chat_store.load_history(session_id, get_settings().chat_history_limit)


def reset_session(session_id: str) -> None:
    """Удаляет чат целиком: историю сообщений и память задачи."""
    chat_store.delete_chat(session_id)


def list_chats() -> list[dict]:
    """Список сохранённых чатов (свежие сверху)."""
    return chat_store.list_chats()


def load_session(session_id: str) -> dict:
    """Снимок сессии для восстановления UI: сообщения + память задачи."""
    return {
        "session_id": session_id,
        "messages": _load_history(session_id),
        "task_state": chat_store.load_task_state(session_id),
    }


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


async def _run_rag_chat(
    session_id: str,
    user_message: str,
    strategy: str,
    options: rag_pipeline.RetrievalOptions | None = None,
    provider: str = llm.DEFAULT_PROVIDER,
    started: float | None = None,
) -> dict:
    """Чат в RAG-режиме: чанки выбранной стратегии и память задачи подмешиваются в вопрос к LLM."""
    history = _load_history(session_id)
    previous_state = chat_store.load_task_state(session_id)
    try:
        state = await task_state.update_state(user_message, history, previous_state)
    except Exception as exc:  # noqa: BLE001 — память задачи не должна ронять чат
        logger.warning("Ошибка обновления памяти задачи: %s", exc)
        state = previous_state or task_state.empty_state()

    try:
        result = await rag.build_rag_reply(
            user_message, strategy, history, options, state, provider=provider
        )
    except rag.RagError as exc:
        return {
            "reply": str(exc),
            "tool_calls": [],
            "chunks": [],
            "task_state": state,
            "error": "rag_error",
        }
    except llm.LLMError as exc:
        return {
            "reply": str(exc),
            "tool_calls": [],
            "chunks": [],
            "task_state": state,
            "error": "llm_error",
        }
    except Exception as exc:  # noqa: BLE001 — не роняем сервер из-за ошибок RAG
        logger.warning("Ошибка RAG-чата: %s", exc)
        return {
            "reply": f"Ошибка RAG-чата: {exc}",
            "tool_calls": [],
            "chunks": [],
            "task_state": state,
            "error": "rag_error",
        }

    chat_store.append_message(session_id, "user", user_message)
    chat_store.append_message(session_id, "assistant", result["reply"])
    chat_store.save_task_state(session_id, state)
    chat = chat_store.get_chat(session_id) or {}
    return {
        "reply": result["reply"],
        "tool_calls": [],
        "chunks": result["chunks"],
        "debug": result.get("debug"),
        "task_state": state,
        "chat_id": session_id,
        "chat_title": chat.get("title"),
        "reasoning": result.get("reasoning"),
        "elapsed_ms": _elapsed_ms(started),
    }


async def run_chat(
    session_id: str,
    user_message: str,
    rag_strategy: str | None = None,
    rag_options: rag_pipeline.RetrievalOptions | None = None,
    llm_provider: str = llm.DEFAULT_PROVIDER,
) -> dict:
    settings = get_settings()
    user_message = (user_message or "").strip()
    rag_strategy = (rag_strategy or "").strip() or None
    provider = llm.normalize_provider(llm_provider)
    started = time.monotonic()

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
    if not llm.is_configured(provider):
        return {
            "reply": (
                "LLM не настроена: добавьте DEEPSEEK_API_KEY в файл .env и перезапустите сервер. "
                "Интерфейс и парсинг при этом работают."
            ),
            "tool_calls": [],
            "error": "llm_not_configured",
        }

    if rag_strategy:
        return await _run_rag_chat(
            session_id, user_message, rag_strategy, rag_options, provider, started
        )

    client = llm.get_client(provider)
    messages: list[dict] = [{"role": "system", "content": _system_prompt()}]
    messages.extend(_load_history(session_id))
    messages.append({"role": "user", "content": user_message})

    tool_events: list[dict] = []
    final_reply = ""
    try:
        for _ in range(max(1, settings.chat_max_iterations)):
            response = await client.chat.completions.create(
                model=llm.chat_model(provider),
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
    except llm.LLMNotConfigured as exc:
        return {"reply": str(exc), "tool_calls": tool_events, "error": "llm_not_configured"}
    except Exception as exc:  # noqa: BLE001 — не роняем сервер из-за ошибок LLM
        logger.warning("Ошибка чата: %s", exc)
        return {"reply": f"Ошибка обращения к LLM: {exc}", "tool_calls": tool_events, "error": "llm_error"}

    final_reply = final_reply or "Модель вернула пустой ответ."
    chat_store.append_message(session_id, "user", user_message)
    chat_store.append_message(session_id, "assistant", final_reply)
    chat = chat_store.get_chat(session_id) or {}
    return {
        "reply": final_reply,
        "tool_calls": tool_events,
        "chunks": [],
        "chat_id": session_id,
        "chat_title": chat.get("title"),
        "elapsed_ms": _elapsed_ms(started),
    }


# --- Стриминг (SSE) ---


def _stream_error(started: float, reply: str, code: str) -> dict:
    return {
        "type": "reply",
        "reply": reply,
        "tool_calls": [],
        "chunks": [],
        "elapsed_ms": _elapsed_ms(started),
        "error": code,
    }


async def _run_agent_chat_stream(session_id: str, user_message: str, provider: str, started: float):
    settings = get_settings()
    messages: list[dict] = [{"role": "system", "content": _system_prompt()}]
    messages.extend(_load_history(session_id))
    messages.append({"role": "user", "content": user_message})

    tool_events: list[dict] = []
    reasoning_parts: list[str] = []
    final_reply = ""

    for _ in range(max(1, settings.chat_max_iterations)):
        result: dict | None = None
        async for event in llm.stream_complete(
            messages,
            provider=provider,
            tools=all_tools_schema(),
            temperature=0.7,
            max_tokens=2000,
            phase="chat",
        ):
            if "done" in event:
                result = event["done"]
            elif event.get("reasoning"):
                reasoning_parts.append(event["reasoning"])
                yield {"type": "thinking", "delta": event["reasoning"]}
        if result is None:
            break
        if not result["tool_calls"]:
            final_reply = result["content"]
            break

        messages.append(
            {
                "role": "assistant",
                "content": result["content"] or "",
                "tool_calls": result["tool_calls"],
            }
        )
        for call in result["tool_calls"]:
            arguments = _parse_arguments(call["function"]["arguments"])
            call_result = await route_tool_call(call["function"]["name"], arguments)
            event_payload = {
                "name": call["function"]["name"],
                "arguments": arguments,
                "result_preview": call_result[:RESULT_PREVIEW_CHARS],
                "result": call_result,
            }
            tool_events.append(event_payload)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": call_result})
            yield {"type": "tool", "event": event_payload}
    else:
        final_reply = (
            "Не удалось завершить обработку за отведённое число шагов вызова инструментов. "
            "Попробуйте переформулировать запрос."
        )

    final_reply = final_reply or "Модель вернула пустой ответ."
    chat_store.append_message(session_id, "user", user_message)
    chat_store.append_message(session_id, "assistant", final_reply)
    chat = chat_store.get_chat(session_id) or {}
    yield {
        "type": "reply",
        "reply": final_reply,
        "tool_calls": tool_events,
        "chunks": [],
        "reasoning": "".join(reasoning_parts).strip() or None,
        "elapsed_ms": _elapsed_ms(started),
        "chat_id": session_id,
        "chat_title": chat.get("title"),
    }


async def _run_rag_chat_stream(
    session_id: str,
    user_message: str,
    strategy: str,
    options: rag_pipeline.RetrievalOptions | None,
    provider: str,
    started: float,
):
    history = _load_history(session_id)
    previous_state = chat_store.load_task_state(session_id)
    try:
        state = await task_state.update_state(user_message, history, previous_state)
    except Exception as exc:  # noqa: BLE001 — память задачи не должна ронять чат
        logger.warning("Ошибка обновления памяти задачи: %s", exc)
        state = previous_state or task_state.empty_state()

    result: dict | None = None
    try:
        async for event in rag.build_rag_reply_stream(
            user_message, strategy, history, options, state, provider=provider
        ):
            if "done" in event:
                result = event["done"]
            elif event.get("reasoning"):
                yield {"type": "thinking", "delta": event["reasoning"]}
    except rag.RagError as exc:
        yield _stream_error(started, str(exc), "rag_error")
        return

    if result is None:
        yield _stream_error(started, "Модель вернула пустой ответ.", "empty")
        return

    chat_store.append_message(session_id, "user", user_message)
    chat_store.append_message(session_id, "assistant", result["reply"])
    chat_store.save_task_state(session_id, state)
    chat = chat_store.get_chat(session_id) or {}
    yield {
        "type": "reply",
        "reply": result["reply"],
        "tool_calls": [],
        "chunks": result["chunks"],
        "debug": result.get("debug"),
        "task_state": state,
        "reasoning": result.get("reasoning"),
        "elapsed_ms": _elapsed_ms(started),
        "chat_id": session_id,
        "chat_title": chat.get("title"),
    }


async def run_chat_stream(
    session_id: str,
    user_message: str,
    rag_strategy: str | None = None,
    rag_options: rag_pipeline.RetrievalOptions | None = None,
    llm_provider: str = llm.DEFAULT_PROVIDER,
):
    """Стрим чата: события SSE (thinking / tool / reply) для веб-клиента."""
    started = time.monotonic()
    settings = get_settings()
    user_message = (user_message or "").strip()
    rag_strategy = (rag_strategy or "").strip() or None
    provider = llm.normalize_provider(llm_provider)

    if not user_message:
        yield _stream_error(started, "Пустое сообщение.", "empty")
        return
    if len(user_message) > settings.chat_max_message_chars:
        yield _stream_error(
            started,
            f"Сообщение слишком длинное (максимум {settings.chat_max_message_chars} символов).",
            "too_long",
        )
        return
    if not _check_rate_limit(session_id):
        yield _stream_error(
            started,
            f"Слишком много сообщений. Лимит — {settings.chat_rate_limit_per_minute} в минуту.",
            "rate_limit",
        )
        return
    if not llm.is_configured(provider):
        yield _stream_error(
            started,
            "LLM не настроена: добавьте DEEPSEEK_API_KEY в файл .env и перезапустите сервер. "
            "Интерфейс и парсинг при этом работают.",
            "llm_not_configured",
        )
        return

    try:
        if rag_strategy:
            async for event in _run_rag_chat_stream(
                session_id, user_message, rag_strategy, rag_options, provider, started
            ):
                yield event
        else:
            async for event in _run_agent_chat_stream(
                session_id, user_message, provider, started
            ):
                yield event
    except llm.LLMError as exc:
        yield _stream_error(started, str(exc), "llm_error")
    except Exception as exc:  # noqa: BLE001 — не роняем сервер из-за ошибок LLM
        logger.warning("Ошибка чата (stream): %s", exc)
        yield _stream_error(started, f"Ошибка обращения к LLM: {exc}", "llm_error")
