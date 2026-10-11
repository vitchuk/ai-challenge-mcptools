"""Провайдеры LLM: облачный DeepSeek (OpenAI SDK) и локальный Ollama (нативный /api/chat).

Все вызовы проходят через `complete`/`stream_complete`, логируются в `llm_log` и
поддерживают параметры генерации (temperature / top_p / top_k / no_think).

Ollama использует нативный `/api/chat`: только там работают `top_k`, `think:false`
(отключение размышлений) и `num_predict`. DeepSeek API не поддерживает `top_k` —
параметр к нему не отправляется.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

import httpx
from openai import AsyncOpenAI

from . import llm_log
from .config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "deepseek"
PROVIDERS = ("deepseek", "ollama")
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 2000


class LLMError(RuntimeError):
    """Ошибка обращения к LLM."""


class LLMNotConfigured(LLMError):
    """Провайдер не настроен (не задан DEEPSEEK_API_KEY)."""


@dataclass
class SamplingParams:
    """Параметры генерации. None — не задано (провайдерский дефолт)."""

    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    max_tokens: int | None = None
    no_think: bool = False


_deepseek_client: AsyncOpenAI | None = None


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
    """Клиент DeepSeek (Ollama работает через httpx — нативный API)."""
    global _deepseek_client
    settings = get_settings()
    if not settings.deepseek_api_key:
        raise LLMNotConfigured(
            "DEEPSEEK_API_KEY не задан. Добавьте ключ в файл .env и перезапустите сервер."
        )
    if _deepseek_client is None:
        _deepseek_client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            timeout=120,
            max_retries=2,
        )
    return _deepseek_client


async def check_ollama_available(timeout: float = 1.5) -> bool:
    """Быстрая проверка, запущен ли локальный Ollama (для статуса в UI)."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
            response = await client.get(f"{settings.ollama_base_url}/api/tags")
            return response.status_code == 200
    except httpx.HTTPError:
        return False


# --- Нормализация tool_calls и reasoning ---


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
    """Приводит tool_calls ответа OpenAI SDK к payload (dict)."""
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


def _normalize_ollama_tool_calls(calls: list[dict] | None) -> list[dict]:
    """tool_calls нативного Ollama → OpenAI-payload (arguments: dict → строка JSON)."""
    normalized: list[dict] = []
    for index, call in enumerate(calls or []):
        function = call.get("function") or {}
        arguments = function.get("arguments")
        if isinstance(arguments, dict):
            arguments = json.dumps(arguments, ensure_ascii=False)
        normalized.append(
            {
                "id": call.get("id") or f"call_{index}",
                "type": "function",
                "function": {
                    "name": function.get("name", "") or "",
                    "arguments": arguments or "{}",
                },
            }
        )
    return normalized


def _arguments_to_dict(raw: object) -> dict:
    """arguments (строка JSON или dict) → dict для нативного Ollama."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _to_ollama_messages(messages: list[dict]) -> list[dict]:
    """OpenAI-сообщения → формат нативного Ollama (tool_calls.arguments как объект)."""
    result: list[dict] = []
    for message in messages:
        item: dict = {"role": message.get("role"), "content": message.get("content") or ""}
        tool_calls = message.get("tool_calls")
        if tool_calls:
            item["tool_calls"] = [
                {
                    "function": {
                        "name": call["function"]["name"],
                        "arguments": _arguments_to_dict(call["function"].get("arguments")),
                    }
                }
                for call in tool_calls
            ]
        result.append(item)
    return result


# --- DeepSeek (OpenAI SDK) ---


def _deepseek_kwargs(messages: list[dict], model: str, tools: list[dict] | None, sampling: SamplingParams) -> dict:
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": sampling.temperature if sampling.temperature is not None else DEFAULT_TEMPERATURE,
        "max_tokens": sampling.max_tokens or DEFAULT_MAX_TOKENS,
    }
    if sampling.top_p is not None:
        kwargs["top_p"] = sampling.top_p
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    return kwargs


async def _deepseek_complete(
    messages: list[dict], model: str, tools: list[dict] | None, sampling: SamplingParams
) -> dict:
    client = get_client("deepseek")
    response = await client.chat.completions.create(**_deepseek_kwargs(messages, model, tools, sampling))
    message = response.choices[0].message
    return {
        "content": (message.content or "").strip(),
        "reasoning": _extract_reasoning(message) or None,
        "tool_calls": _normalize_tool_calls(message),
    }


async def _deepseek_stream(messages, model, tools, sampling, tool_calls: list[dict]):
    client = get_client("deepseek")
    kwargs = _deepseek_kwargs(messages, model, tools, sampling)
    kwargs["stream"] = True
    stream = await client.chat.completions.create(**kwargs)
    acc: dict[int, dict] = {}
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        reasoning = _extract_reasoning(delta)
        content = getattr(delta, "content", None) or ""
        for call in getattr(delta, "tool_calls", None) or []:
            index = call.index if call.index is not None else 0
            item = acc.setdefault(index, {"id": None, "name": "", "arguments": ""})
            if getattr(call, "id", None):
                item["id"] = call.id
            function = getattr(call, "function", None)
            if function is not None:
                if getattr(function, "name", None):
                    item["name"] = function.name
                if getattr(function, "arguments", None):
                    item["arguments"] += function.arguments
        if reasoning or content:
            yield reasoning, content
    tool_calls[:] = _finalize_tool_calls(acc)


# --- Ollama (нативный /api/chat) ---


def _ollama_payload(
    messages: list[dict], model: str, tools: list[dict] | None, sampling: SamplingParams, *, stream: bool
) -> dict:
    options: dict = {}
    if sampling.temperature is not None:
        options["temperature"] = sampling.temperature
    if sampling.top_p is not None:
        options["top_p"] = sampling.top_p
    if sampling.top_k:
        options["top_k"] = sampling.top_k
    max_tokens = sampling.max_tokens or get_settings().ollama_chat_max_tokens
    if max_tokens:
        options["num_predict"] = max_tokens

    payload: dict = {
        "model": model,
        "messages": _to_ollama_messages(messages),
        "stream": stream,
    }
    if options:
        payload["options"] = options
    if sampling.no_think:
        payload["think"] = False
    if tools:
        payload["tools"] = tools
    return payload


async def _ollama_complete(
    messages: list[dict], model: str, tools: list[dict] | None, sampling: SamplingParams
) -> dict:
    settings = get_settings()
    payload = _ollama_payload(messages, model, tools, sampling, stream=False)
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
        response = await client.post(f"{settings.ollama_base_url}/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()
    message = data.get("message") or {}
    return {
        "content": (message.get("content") or "").strip(),
        "reasoning": (message.get("thinking") or "").strip() or None,
        "tool_calls": _normalize_ollama_tool_calls(message.get("tool_calls")),
    }


async def _ollama_stream(messages, model, tools, sampling, tool_calls: list[dict]):
    settings = get_settings()
    payload = _ollama_payload(messages, model, tools, sampling, stream=True)
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
        async with client.stream(
            "POST", f"{settings.ollama_base_url}/api/chat", json=payload
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                message = data.get("message") or {}
                calls = message.get("tool_calls")
                if calls:
                    tool_calls[:] = _normalize_ollama_tool_calls(calls)
                reasoning = message.get("thinking") or ""
                content = message.get("content") or ""
                if reasoning or content:
                    yield reasoning, content
                if data.get("done"):
                    break


# --- Публичный интерфейс ---


async def complete(
    messages: list[dict],
    *,
    provider: str = DEFAULT_PROVIDER,
    tools: list[dict] | None = None,
    sampling: SamplingParams | None = None,
    phase: str = "aux",
) -> dict:
    """Один вызов LLM без стрима. Возвращает {content, reasoning, tool_calls}."""
    provider = normalize_provider(provider)
    sampling = sampling or SamplingParams()
    model = chat_model(provider)
    started = time.monotonic()
    try:
        if provider == "ollama":
            result = await _ollama_complete(messages, model, tools, sampling)
        else:
            result = await _deepseek_complete(messages, model, tools, sampling)
    except LLMNotConfigured:
        raise
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
    sampling: SamplingParams | None = None,
    phase: str = "chat",
):
    """Стрим вызова LLM.

    Async-генератор отдаёт дельты `{"reasoning": str, "content": str}`,
    а в конце — `{"done": {content, reasoning, tool_calls}}`. Вызов логируется.
    """
    provider = normalize_provider(provider)
    sampling = sampling or SamplingParams()
    model = chat_model(provider)
    started = time.monotonic()
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls: list[dict] = []

    try:
        if provider == "ollama":
            agen = _ollama_stream(messages, model, tools, sampling, tool_calls)
        else:
            agen = _deepseek_stream(messages, model, tools, sampling, tool_calls)
        async for reasoning, content in agen:
            if reasoning:
                reasoning_parts.append(reasoning)
            if content:
                content_parts.append(content)
            if reasoning or content:
                yield {"reasoning": reasoning, "content": content}
    except LLMNotConfigured:
        raise
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
        "tool_calls": tool_calls,
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
        sampling=SamplingParams(temperature=temperature, max_tokens=max_tokens),
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
