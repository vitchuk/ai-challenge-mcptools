"""Стратегии поиска RAG поверх существующего векторного поиска.

Модуль НЕ импортирует rag.py: ретривер передаётся вызывающим кодом
(`build_rag_reply`) как callable, чтобы не возникало циклических импортов.

Этапы:
- QueryRewriter  — LLM переписывает вопрос в поисковый запрос (rewrite_query);
- Retriever      — существующий косинусный поиск (rag.search), передаётся извне;
- SimilarityFilter — отброс кандидатов ниже порога similarity;
- Reranker       — LLM оценивает релевантность каждого кандидата (rerank_candidates);
- оркестрация    — run_retrieval по стратегии baseline/query-rewrite/similarity-filter/
                   query-rewrite-rerank.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from . import deepseek

logger = logging.getLogger(__name__)

# Стратегии поиска (retrieval pipeline). Не путать со стратегиями чанкинга из rag.py.
RETRIEVAL_STRATEGIES: dict[str, str] = {
    "baseline": "A. Baseline — поиск → Top_K → LLM (как было)",
    "query-rewrite": "B. Query Rewrite — переписывание вопроса → поиск → Top_K → LLM",
    "similarity-filter": "C. Similarity Filter — поиск Top_K до → порог → Top_K после → LLM",
    "query-rewrite-rerank": "D. Query Rewrite + Reranker — rewrite → поиск → фильтр → reranker → LLM",
}

# Сигнатура ретривера: (поисковый запрос, top_k) -> список чанков с полем score.
Retriever = Callable[[str, int], Awaitable[list[dict]]]


class PipelineError(RuntimeError):
    """Ошибка этапа пайплайна (валидация, rewrite, rerank)."""


@dataclass
class RetrievalOptions:
    """Параметры стратегии поиска. Все поля, кроме strategy, опциональны."""

    strategy: str = "baseline"
    top_k: int | None = None
    top_k_before: int | None = None
    top_k_after: int | None = None
    top_k_final: int | None = None
    similarity_threshold: float | None = None
    reranker_threshold: float | None = None

    def validate(self) -> None:
        if self.strategy not in RETRIEVAL_STRATEGIES:
            raise PipelineError(
                f"Неизвестная стратегия поиска: {self.strategy} "
                f"(доступны: {', '.join(RETRIEVAL_STRATEGIES)})"
            )
        for name, value in (
            ("top_k", self.top_k),
            ("top_k_before", self.top_k_before),
            ("top_k_after", self.top_k_after),
            ("top_k_final", self.top_k_final),
        ):
            if value is not None and value < 1:
                raise PipelineError(f"{name} должен быть >= 1 (получено {value})")
        for name, value in (
            ("similarity_threshold", self.similarity_threshold),
            ("reranker_threshold", self.reranker_threshold),
        ):
            if value is not None and not 0.0 <= value <= 1.0:
                raise PipelineError(f"{name} должен быть в диапазоне 0..1 (получено {value})")
        final_k = self.top_k_final if self.top_k_final is not None else self.top_k_after
        if self.top_k_before is not None and final_k is not None and self.top_k_before < final_k:
            raise PipelineError(
                f"top_k_before ({self.top_k_before}) не может быть меньше итогового Top_K ({final_k})"
            )


# --- Query Rewrite ---

REWRITE_SYSTEM_PROMPT = (
    "Ты — оптимизатор поисковых запросов для векторного поиска по базе статей. "
    "Перепиши вопрос пользователя в один самодостаточный поисковый запрос на русском языке: "
    "раскрой местоимения и указательные слова («это», «он», «такой») с опорой на историю диалога, "
    "добавь ключевые термины. Верни ТОЛЬКО переписанный запрос — без пояснений, кавычек и префиксов."
)

_MAX_REWRITE_CHARS = 400
_REWRITE_HISTORY_MESSAGES = 6


async def rewrite_query(query: str, history: list[dict] | None = None) -> str:
    """Переписывает вопрос в поисковый запрос.

    При сбое LLM/пустом ответе бросает LLMError/PipelineError — вызывающий код
    делает fallback на исходный запрос.
    """
    context_lines: list[str] = []
    for message in list(history or [])[-_REWRITE_HISTORY_MESSAGES:]:
        role = message.get("role")
        content = (message.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        label = "Пользователь" if role == "user" else "Ассистент"
        context_lines.append(f"{label}: {content[:300]}")
    prompt = ""
    if context_lines:
        prompt += "История диалога (для контекста):\n" + "\n".join(context_lines) + "\n\n"
    prompt += f"Вопрос пользователя: {query}\n\nПереписанный поисковый запрос:"

    rewritten = await deepseek.complete_text(
        REWRITE_SYSTEM_PROMPT, prompt, temperature=0.0, max_tokens=200
    )
    rewritten = rewritten.strip().strip('"').strip("«»").strip()
    if not rewritten:
        raise PipelineError("Query rewrite вернул пустой результат")
    return rewritten[:_MAX_REWRITE_CHARS]


# --- Reranker (LLM-оценка релевантности, один батч-запрос) ---

RERANK_SYSTEM_PROMPT = (
    "Ты — reranker. Оцени, насколько каждый фрагмент релевантен вопросу пользователя, "
    "по шкале от 0.0 (совсем не по теме) до 1.0 (прямой ответ на вопрос). "
    "Верни СТРОГО JSON-массив без пояснений в формате "
    '[{"index": 1, "score": 0.87}, {"index": 2, "score": 0.13}] — '
    "по одному объекту на каждый фрагмент."
)

_RERANK_CHARS = 800
_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def _format_candidates(hits: list[dict]) -> str:
    blocks: list[str] = []
    for index, hit in enumerate(hits, start=1):
        text = (hit.get("text") or "").strip().replace("\n", " ")
        blocks.append(f"[{index}] {text[:_RERANK_CHARS]}")
    return "\n\n".join(blocks)


def _parse_scores(raw: str, count: int) -> list[float | None]:
    match = _JSON_ARRAY_RE.search(raw)
    payload = match.group(0) if match else raw
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise PipelineError(f"Reranker вернул не JSON: {raw[:120]}") from exc
    if not isinstance(data, list):
        raise PipelineError("Reranker вернул не массив")
    scores: list[float | None] = [None] * count
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
            score = float(item.get("score"))
        except (TypeError, ValueError):
            continue
        if 1 <= index <= count:
            scores[index - 1] = max(0.0, min(1.0, score))
    if all(score is None for score in scores):
        raise PipelineError("Reranker не вернул ни одной корректной оценки")
    return scores


async def rerank_candidates(query: str, hits: list[dict]) -> list[float | None]:
    """Возвращает оценку релевантности 0..1 для каждого кандидата (batch-запрос к LLM)."""
    if not hits:
        return []
    user_prompt = (
        f"Вопрос пользователя: {query}\n\n"
        f"Фрагменты:\n{_format_candidates(hits)}\n\n"
        "Оценки в формате JSON:"
    )
    raw = await deepseek.complete_text(
        RERANK_SYSTEM_PROMPT, user_prompt, temperature=0.0, max_tokens=800
    )
    return _parse_scores(raw, len(hits))


# --- Оркестрация ---


def _similarity_filter(hits: list[dict], threshold: float | None) -> list[dict]:
    """Оставляет чанки со score >= threshold (косинусная similarity)."""
    if threshold is None:
        return list(hits)
    return [hit for hit in hits if float(hit.get("score", 0.0)) >= threshold]


def _debug(
    options: RetrievalOptions,
    *,
    original_query: str,
    rewritten_query: str | None,
    rewrite_fallback: bool,
    reranker_fallback: bool | None,
    counts: dict,
) -> dict:
    return {
        "retrieval_strategy": options.strategy,
        "original_query": original_query,
        "rewritten_query": rewritten_query,
        "rewrite_fallback": rewrite_fallback,
        "reranker_fallback": reranker_fallback,
        "params": {
            "top_k": options.top_k,
            "top_k_before": options.top_k_before,
            "similarity_threshold": options.similarity_threshold,
            "top_k_after": options.top_k_after,
            "top_k_final": options.top_k_final,
            "reranker_threshold": options.reranker_threshold,
        },
        "counts": counts,
    }


def _counts(retrieved: int, after_filter: int, after_rerank: int, final: int) -> dict:
    return {
        "retrieved": retrieved,
        "after_similarity_filter": after_filter,
        "after_reranker_filter": after_rerank,
        "final": final,
    }


async def run_retrieval(
    query: str,
    retrieve: Retriever,
    options: RetrievalOptions,
    *,
    default_top_k: int = 5,
    history: list[dict] | None = None,
) -> tuple[list[dict], dict]:
    """Выполняет стратегию поиска; возвращает (финальные чанки, debug-словарь)."""
    options.validate()
    original_query = query
    rewritten_query: str | None = None
    rewrite_fallback = False
    search_query = original_query

    if options.strategy in ("query-rewrite", "query-rewrite-rerank"):
        try:
            rewritten_query = await rewrite_query(original_query, history)
            search_query = rewritten_query
        except (deepseek.LLMError, PipelineError) as exc:
            logger.warning("Query rewrite не удался, используем исходный запрос: %s", exc)
            rewrite_fallback = True
            search_query = original_query

    if options.strategy == "baseline":
        top_k = max(1, options.top_k or default_top_k)
        retrieved = await retrieve(original_query, top_k)
        count = len(retrieved)
        debug = _debug(
            options,
            original_query=original_query,
            rewritten_query=None,
            rewrite_fallback=False,
            reranker_fallback=None,
            counts=_counts(count, count, count, count),
        )
        return retrieved, debug

    if options.strategy == "query-rewrite":
        top_k = max(1, options.top_k or default_top_k)
        retrieved = await retrieve(search_query, top_k)
        filtered = _similarity_filter(retrieved, options.similarity_threshold)
        debug = _debug(
            options,
            original_query=original_query,
            rewritten_query=rewritten_query,
            rewrite_fallback=rewrite_fallback,
            reranker_fallback=None,
            counts=_counts(len(retrieved), len(filtered), len(filtered), len(filtered)),
        )
        return filtered, debug

    if options.strategy == "similarity-filter":
        before = max(1, options.top_k_before or default_top_k)
        after = max(1, options.top_k_after or default_top_k)
        retrieved = await retrieve(original_query, before)
        filtered = _similarity_filter(retrieved, options.similarity_threshold)
        final = filtered[:after]
        debug = _debug(
            options,
            original_query=original_query,
            rewritten_query=None,
            rewrite_fallback=False,
            reranker_fallback=None,
            counts=_counts(len(retrieved), len(filtered), len(filtered), len(final)),
        )
        return final, debug

    # query-rewrite-rerank
    before = max(1, options.top_k_before or default_top_k)
    final_k = max(1, options.top_k_final or default_top_k)
    retrieved = await retrieve(search_query, before)
    filtered = _similarity_filter(retrieved, options.similarity_threshold)

    reranker_fallback = False
    hits = list(filtered)
    try:
        scores = await rerank_candidates(search_query, filtered)
        hits = [{**hit, "reranker_score": score} for hit, score in zip(filtered, scores)]
        # None-оценки уходят в конец; среди оценённых — по убыванию reranker score.
        hits.sort(
            key=lambda hit: (
                hit.get("reranker_score") is not None,
                hit.get("reranker_score") or 0.0,
            ),
            reverse=True,
        )
    except (deepseek.LLMError, PipelineError) as exc:
        logger.warning("Reranker недоступен, сохраняем порядок similarity: %s", exc)
        reranker_fallback = True

    after_rerank = len(hits)
    if not reranker_fallback and options.reranker_threshold is not None:
        hits = [
            hit
            for hit in hits
            if float(hit.get("reranker_score") or 0.0) >= options.reranker_threshold
        ]
    final = hits[:final_k]
    debug = _debug(
        options,
        original_query=original_query,
        rewritten_query=rewritten_query,
        rewrite_fallback=rewrite_fallback,
        reranker_fallback=reranker_fallback,
        counts=_counts(len(retrieved), len(filtered), after_rerank, len(final)),
    )
    return final, debug
