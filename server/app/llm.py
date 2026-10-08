"""Провайдеры LLM: облачный DeepSeek и локальный Ollama (OpenAI-совместимый API).

Оба провайдера работают через `AsyncOpenAI`; для Ollama используется
эндпоинт `{ollama_base_url}/v1`. По умолчанию — DeepSeek.

Все вызовы проходят через `complete`/`stream_complete` и логируются в `llm_log`
(контекст запроса + ответ) для вкладки LOG в веб-клиенте.
"""

from __future__ import annotations

import logging
import time

import httpx
from openai import AsyncOpenAI

from . import llm_log
from .config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "deepseek"
PROVIDERS = ("deepseek", "ollama")


class LLMError(RuntimeError):
    """Ошибка обращения к LLM."""


class LLMNotConfigured(LLMError):
    """Провайдер не настроен (не задан DEEPSEEK_API_KEY)."""


_clients: dict[str, AsyncOpenAI] = {}


def normalize_provider(name: str | None) -> str:
    """Приводит имя провайдера к допустимому; неизвестное — DeepSeek."""
    provider = (name or DEFAULT_PROVIDER).strip().lower()
    return provider if provider in PROVIDERS else DEFAULT_PROVIDER


def is_configured(provider: str = DEFAULT_PROVIDER) -> bool:
    """Ollama не требует ключа; DeepSeek требует DEEPSEEK_API_KEY."""
    if normalize_provider(provider) == "ollama":
        return True
    return bool(get_settings().deepseek_api_key)


def chat_model(provider: str = DEFAULT_PROVIDER) -> str:
    """Имя чат-модели выбранного провайдера."""
    settings = get_settings()
    if normalize_provider(provider) == "ollama":
        return settings.ollama_chat_model
    return settings.deepseek_model


def get_client(provider: str = DEFAULT_PROVIDER) -> AsyncOpenAI:
    provider = normalize_provider(provider)
    settings = get_settings()
    if provider == "ollama":
        if "ollama" not in _clients:
            _clients["ollama"] = AsyncOpenAI(
                api_key="ollama",
                base_url=f"{settings.ollama_base_url}/v1",
                timeout=300,
                max_retries=1,
            )
        return _clients["ollama"]

    if not settings.deepseek_api_key:
        raise LLMNotConfigured(
            "DEEPSEEK_API_KEY не задан. Добавьте ключ в файл .env и перезапустите сервер."
        )
    if "deepseek" not in _clients:
        _clients["deepseek"] = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            timeout=120,
            max_retries=2,
        )
    return _clients["deepseek"]


async def check_ollama_available(timeout: float = 1.5) -> bool:
    """Быстрая проверка, запущен ли локальный Ollama (для статуса в UI)."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
            response = await client.get(f"{settings.ollama_base_url}/api/tags")
            return response.status_code == 200
    except httpx.HTTPError:
        return False


def _extract_reasoning(source) -> str:
    """Достаёт текст размышлений из delta/message (Ollama: reasoning, DeepSeek: reasoning_content)."""
    for attr in ("reasoning", "reasoning_content"):
        value = getattr(source, attr, None)
        if value:
            return value
    extra = getattr(source, "model_extra", None) or {}
    for attr in ("reasoning", "reasoning_content"):
        value = extra.get(attr)
        if value:
            return value
    return ""


def _normalize_tool_calls(message) -> list[dict]:
    """Приводит tool_calls ответа к OpenAI-payload (dict)."""
    calls = getattr(message, "tool_calls", None)
    if not calls:
        return []
    normalized: list[dict] = []
    for call in calls:
        function = getattr(call, "function", None)
        normalized.append(
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": getattr(function, "name", "") or "",
                    "arguments": getattr(function, "arguments", "") or "{}",
                },
            }
        )
    return normalized


def _finalize_tool_calls(acc: dict[int, dict]) -> list[dict]:
    """Собирает накопленные в стриме фрагменты tool_calls в готовый список."""
    calls: list[dict] = []
    for index in sorted(acc):
        item = acc[index]
        calls.append(
            {
                "id": item["id"] or f"call_{index}",
                "type": "function",
                "function": {
                    "name": item["name"],
                    "arguments": item["arguments"] or "{}",
                },
            }
        )
    return calls


async def complete(
    messages: list[dict],
    *,
    provider: str = DEFAULT_PROVIDER,
    tools: list[dict] | None = None,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    phase: str = "aux",
) -> dict:
    """Один вызов LLM без стрима. Возвращает {content, reasoning, tool_calls}."""
    provider = normalize_provider(provider)
    model = chat_model(provider)
    client = get_client(provider)
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    started = time.monotonic()
    try:
        response = await client.chat.completions.create(**kwargs)
        message = response.choices[0].message
        result = {
            "content": (message.content or "").strip(),
            "reasoning": _extract_reasoning(message) or None,
            "tool_calls": _normalize_tool_calls(message),
        }
    except Exception as exc:  # noqa: BLE001
        llm_log.log_call(
            phase=phase,
            provider=provider,
            model=model,
            messages=messages,
            tools_count=len(tools or []),
            duration_ms=(time.monotonic() - started) * 1000,
            error=str(exc),
        )
        logger.warning("Ошибка LLM (%s): %s", provider, exc)
        raise LLMError(f"Ошибка LLM ({provider}): {exc}") from exc

    llm_log.log_call(
        phase=phase,
        provider=provider,
        model=model,
        messages=messages,
        response=result,
        tools_count=len(tools or []),
        duration_ms=(time.monotonic() - started) * 1000,
    )
    return result


async def stream_complete(
    messages: list[dict],
    *,
    provider: str = DEFAULT_PROVIDER,
    tools: list[dict] | None = None,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    phase: str = "chat",
):
    """Стрим вызова LLM.

    Async-генератор отдаёт дельты `{"reasoning": str, "content": str}`,
    а в конце — `{"done": {content, reasoning, tool_calls}}`. Вызов логируется.
    """
    provider = normalize_provider(provider)
    model = chat_model(provider)
    client = get_client(provider)
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    started = time.monotonic()
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_acc: dict[int, dict] = {}

    try:
        stream = await client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            reasoning = _extract_reasoning(delta)
            content = getattr(delta, "content", None) or ""

            for call in getattr(delta, "tool_calls", None) or []:
                index = call.index if call.index is not None else 0
                item = tool_acc.setdefault(
                    index, {"id": None, "name": "", "arguments": ""}
                )
                if getattr(call, "id", None):
                    item["id"] = call.id
                function = getattr(call, "function", None)
                if function is not None:
                    if getattr(function, "name", None):
                        item["name"] = function.name
                    if getattr(function, "arguments", None):
                        item["arguments"] += function.arguments

            if reasoning:
                reasoning_parts.append(reasoning)
            if content:
                content_parts.append(content)
            if reasoning or content:
                yield {"reasoning": reasoning, "content": content}
    except Exception as exc:  # noqa: BLE001
        llm_log.log_call(
            phase=phase,
            provider=provider,
            model=model,
            messages=messages,
            tools_count=len(tools or []),
            duration_ms=(time.monotonic() - started) * 1000,
            error=str(exc),
        )
        logger.warning("Ошибка LLM (%s, stream): %s", provider, exc)
        raise LLMError(f"Ошибка LLM ({provider}): {exc}") from exc

    result = {
        "content": "".join(content_parts).strip(),
        "reasoning": "".join(reasoning_parts).strip() or None,
        "tool_calls": _finalize_tool_calls(tool_acc),
    }
    llm_log.log_call(
        phase=phase,
        provider=provider,
        model=model,
        messages=messages,
        response=result,
        tools_count=len(tools or []),
        duration_ms=(time.monotonic() - started) * 1000,
    )
    yield {"done": result}


async def complete_messages(
    messages: list[dict],
    *,
    provider: str = DEFAULT_PROVIDER,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    phase: str = "aux",
) -> str:
    """Запрос к LLM по готовому списку сообщений — без инструментов."""
    result = await complete(
        messages,
        provider=provider,
        temperature=temperature,
        max_tokens=max_tokens,
        phase=phase,
    )
    return result["content"]


async def complete_text(
    system_prompt: str,
    user_prompt: str,
    *,
    provider: str = DEFAULT_PROVIDER,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    phase: str = "aux",
) -> str:
    """Обычный запрос без инструментов — для саммаризации и служебных задач."""
    return await complete_messages(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        provider=provider,
        temperature=temperature,
        max_tokens=max_tokens,
        phase=phase,
    )
