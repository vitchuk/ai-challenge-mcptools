"""Тонкая обёртка над DeepSeek API (OpenAI-совместимый интерфейс)."""

from __future__ import annotations

import logging

from openai import AsyncOpenAI

from .config import get_settings

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


class LLMError(RuntimeError):
    """Ошибка обращения к LLM."""


class LLMNotConfigured(LLMError):
    """Не задан DEEPSEEK_API_KEY."""


def is_configured() -> bool:
    return bool(get_settings().deepseek_api_key)


def get_client() -> AsyncOpenAI:
    global _client
    settings = get_settings()
    if not settings.deepseek_api_key:
        raise LLMNotConfigured(
            "DEEPSEEK_API_KEY не задан. Добавьте ключ в файл .env и перезапустите сервер."
        )
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            timeout=120,
            max_retries=2,
        )
    return _client


async def complete_messages(
    messages: list[dict],
    *,
    temperature: float = 0.3,
    max_tokens: int = 2000,
) -> str:
    """Запрос к LLM по готовому списку сообщений — без инструментов."""
    settings = get_settings()
    client = get_client()
    try:
        response = await client.chat.completions.create(
            model=settings.deepseek_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ошибка DeepSeek API: %s", exc)
        raise LLMError(f"Ошибка DeepSeek API: {exc}") from exc

    return (response.choices[0].message.content or "").strip()


async def complete_text(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float = 0.3,
    max_tokens: int = 2000,
) -> str:
    """Обычный запрос без инструментов — для саммаризации."""
    return await complete_messages(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
