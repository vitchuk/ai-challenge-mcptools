"""RAG-пайплайн: чанкинг pikabu-txt.md, эмбеддинги через ollama, JSON-индексы по стратегиям.

Каждая стратегия чанкинга складывает результат в свою папку
server/data/rag/<strategy>/index.json (чанки + векторы), чтобы UI мог
переключаться между стратегиями и работать с данными каждой из них.

CLI (из папки server): ..\\.venv\\Scripts\\python.exe -m app.rag build|list|search
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import llm, rag_pipeline, task_state
from .config import RagSettings, get_settings

logger = logging.getLogger(__name__)

# Стратегии чанкинга. fixed — скользящее окно по предложениям с перекрытием;
# paragraph — агрегация целых абзацев без перекрытия (естественные границы).
STRATEGIES: dict[str, str] = {
    "fixed": "Скользящее окно ~750 токенов с перекрытием 150, границы по предложениям",
    "paragraph": "Агрегация целых абзацев до 1000 токенов, без перекрытия",
}


class RagError(RuntimeError):
    """Ошибка RAG-пайплайна."""


# --- Разбор источника (pikabu-txt.md) ---


@dataclass
class Article:
    """Статья из pikabu-txt.md."""

    title: str
    url: str | None
    author: str | None
    rating: int | None
    date: str | None
    story_id: int | None
    paragraphs: list[str]

    @property
    def text(self) -> str:
        return "\n\n".join(self.paragraphs)


_META_RE = re.compile(r"^\*(?P<meta>.+)\*$")
_STORY_ID_RE = re.compile(r"_(\d+)$")
_ARTICLE_SPLIT_RE = re.compile(r"(?m)^---\s*$")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")
# Предложение кончается на .!?…»), а дальше — с заглавной/кавычки/цифры.
_SENTENCE_RE = re.compile(r"(?<=[.!?…»)])\s+(?=[А-ЯЁA-Z«\"(„\d])")


def _parse_meta(line: str) -> dict:
    """Мета-строка '*url | автор: X | рейтинг: N | дата: YYYY-MM-DD*' -> словарь."""
    result: dict = {"url": None, "author": None, "rating": None, "date": None}
    match = _META_RE.match(line.strip())
    if not match:
        return result
    for part in match.group("meta").split("|"):
        part = part.strip()
        if part.startswith("http"):
            result["url"] = part
        elif part.startswith(("автор:", "рейтинг:", "дата:")):
            key, _, value = part.partition(":")
            value = value.strip()
            if key == "автор":
                result["author"] = value or None
            elif key == "рейтинг":
                try:
                    result["rating"] = int(value)
                except ValueError:
                    result["rating"] = None
            else:
                result["date"] = value or None
    return result


def parse_source(path: Path) -> list[Article]:
    """Разбирает pikabu-txt.md на статьи: блоки между линиями '---'.

    Блок: '## Заголовок', мета-строка '*url | автор | рейтинг | дата*', абзацы текста.
    """
    if not path.is_file():
        raise RagError(f"Файл-источник не найден: {path}")
    text = path.read_text(encoding="utf-8")
    articles: list[Article] = []
    for block in _ARTICLE_SPLIT_RE.split(text)[1:]:  # первый блок — шапка файла
        lines = block.splitlines()
        header_at = next((i for i, line in enumerate(lines) if line.startswith("## ")), None)
        if header_at is None:
            continue
        title = lines[header_at][3:].strip()
        body_lines = lines[header_at + 1 :]
        meta = {"url": None, "author": None, "rating": None, "date": None}
        first_at = next((i for i, line in enumerate(body_lines) if line.strip()), None)
        if first_at is not None:
            first = body_lines[first_at].strip()
            if first.startswith("*") and first.endswith("*") and len(first) > 2:
                meta = _parse_meta(first)
                body_lines = body_lines[first_at + 1 :]
        body = "\n".join(body_lines).strip()
        paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(body) if p.strip()]
        story_id = None
        if meta["url"] and (match := _STORY_ID_RE.search(meta["url"])):
            story_id = int(match.group(1))
        articles.append(
            Article(
                title=title,
                url=meta["url"],
                author=meta["author"],
                rating=meta["rating"],
                date=meta["date"],
                story_id=story_id,
                paragraphs=paragraphs,
            )
        )
    if not articles:
        raise RagError(f"В {path.name} не найдено статей в формате '## Заголовок'")
    return articles


# --- Чанкинг ---


def estimate_tokens(text: str, chars_per_token: float) -> int:
    """Приблизительный счёт токенов: русские тексты в BPE-токенизаторах ~3 симв./токен."""
    return max(1, round(len(text) / chars_per_token))


def _split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_RE.split(text) if s.strip()]


def _hard_split(text: str, params: RagSettings) -> list[tuple[str, int]]:
    """Режет сверхдлинное предложение по символам на куски <= max_tokens."""
    limit = int(params.max_tokens * params.chars_per_token)
    result: list[tuple[str, int]] = []
    for start in range(0, len(text), limit):
        part = text[start : start + limit]
        result.append((part, estimate_tokens(part, params.chars_per_token)))
    return result


def _windows(
    units: list[tuple[str, int]],
    params: RagSettings,
    overlap_tokens: int,
    joiner: str,
) -> list[tuple[str, int]]:
    """Режет последовательность единиц (текст, токены) на чанки в диапазоне 500–1000.

    Целимся в середину диапазона, чтобы чанки и хвост не вылезали за границы.
    Перекрытие — хвост предыдущего чанка (не больше overlap_tokens, минимум одно
    предложение). Сверхдлинные единицы должны быть нарезаны заранее (_hard_split).
    """
    total = sum(t for _, t in units)
    if total <= params.max_tokens:
        # Статья целиком в один чанк (короткая статья может быть меньше 500 токенов).
        return [(joiner.join(u for u, _ in units), total)]

    mid = (params.min_tokens + params.max_tokens) / 2
    n = max(2, math.ceil(total / mid))
    balanced = total / n

    chunks: list[tuple[str, int]] = []
    cur: list[tuple[str, int]] = []
    cur_t = 0
    fresh = 0  # новых единиц после последнего сброса (чистое перекрытие не эмитим)

    def emit() -> None:
        nonlocal cur, cur_t, fresh
        chunks.append((joiner.join(u for u, _ in cur), cur_t))
        tail: list[tuple[str, int]] = []
        tail_t = 0
        if overlap_tokens > 0 and len(cur) > 1:  # одно предложение = весь чанк, перекрытие бессмысленно
            for unit, t in reversed(cur):
                if tail and tail_t + t > overlap_tokens:
                    break
                tail.insert(0, (unit, t))
                tail_t += t
                if tail_t >= overlap_tokens:
                    break
        cur, cur_t, fresh = tail, tail_t, 0

    for unit, t in units:
        if cur and fresh and cur_t + t > params.max_tokens and cur_t > overlap_tokens:
            emit()
            continue  # единицу добавим уже в новое окно
        cur.append((unit, t))
        cur_t += t
        fresh += 1
        if cur_t >= balanced:
            emit()
    if fresh:  # остаток; окно из одного перекрытия не дублируем
        text = joiner.join(u for u, _ in cur)
        if cur_t < params.min_tokens and chunks and chunks[-1][1] + cur_t <= params.max_tokens:
            prev_text, prev_t = chunks[-1]
            chunks[-1] = (f"{prev_text}{joiner}{text}", prev_t + cur_t)
        else:
            chunks.append((text, cur_t))
    return chunks


def chunk_article_fixed(article: Article, params: RagSettings) -> list[tuple[str, int]]:
    """Стратегия fixed: скользящее окно по предложениям с перекрытием."""
    units: list[tuple[str, int]] = []
    for paragraph in article.paragraphs:
        for sentence in _split_sentences(paragraph):
            t = estimate_tokens(sentence, params.chars_per_token)
            if t > params.max_tokens:
                units.extend(_hard_split(sentence, params))
            else:
                units.append((sentence, t))
    return _windows(units, params, params.overlap_tokens, " ")


def chunk_article_paragraph(article: Article, params: RagSettings) -> list[tuple[str, int]]:
    """Стратегия paragraph: агрегация целых абзацев, без перекрытия."""
    units: list[tuple[str, int]] = []
    for paragraph in article.paragraphs:
        t = estimate_tokens(paragraph, params.chars_per_token)
        if t > params.max_tokens:
            # Сверхдлинный абзац режем окнами по предложениям, тоже без перекрытия.
            pieces: list[tuple[str, int]] = []
            for sentence in _split_sentences(paragraph):
                st = estimate_tokens(sentence, params.chars_per_token)
                if st > params.max_tokens:
                    pieces.extend(_hard_split(sentence, params))
                else:
                    pieces.append((sentence, st))
            units.extend(_windows(pieces, params, 0, " "))
        else:
            units.append((paragraph, t))
    return _windows(units, params, 0, "\n\n")


CHUNKERS = {
    "fixed": chunk_article_fixed,
    "paragraph": chunk_article_paragraph,
}


def build_chunks(
    strategy: str, articles: list[Article], params: RagSettings
) -> tuple[list[dict], int]:
    """Нарезает все статьи на чанки; возвращает (чанки, число отброшенных статей)."""
    chunker = CHUNKERS[strategy]
    chunks: list[dict] = []
    dropped = 0
    for article in articles:
        if estimate_tokens(article.text, params.chars_per_token) < params.min_chunk_tokens:
            dropped += 1  # мем без текста — индексировать нечего
            continue
        pieces = chunker(article, params)
        title_tokens = estimate_tokens(f"{article.title}\n\n", params.chars_per_token)
        for index, (text, tokens) in enumerate(pieces):
            chunk_id = f"{strategy}_{len(chunks) + 1:03d}"
            chunks.append(
                {
                    "id": chunk_id,
                    "text": f"{article.title}\n\n{text}",
                    "tokens": tokens + title_tokens,
                    "metadata": {
                        "chunk_id": chunk_id,
                        "url": article.url,
                        "author": article.author,
                        "rating": article.rating,
                        "date": article.date,
                        "title": article.title,
                        "story_id": article.story_id,
                        "strategy": strategy,
                        "chunk_index": index,
                        "article_chunks": len(pieces),
                    },
                }
            )
    return chunks, dropped


# --- Эмбеддинги (ollama) ---


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else vector


async def embed_texts(
    texts: list[str],
    *,
    model: str,
    base_url: str,
    batch_size: int,
    timeout: float,
) -> list[list[float]]:
    """Эмбеддинги через ollama /api/embed (батчами); векторы нормализованы (L2)."""
    vectors: list[list[float]] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            try:
                response = await client.post(
                    f"{base_url}/api/embed", json={"model": model, "input": batch}
                )
            except httpx.HTTPError as exc:
                raise RagError(
                    f"ollama недоступен ({base_url}): {exc}. "
                    "Проверьте, что сервер запущен и модель скачана (ollama pull)"
                ) from exc
            if response.status_code != 200:
                raise RagError(
                    f"ollama /api/embed -> HTTP {response.status_code}: {response.text[:200]}"
                )
            embeddings = response.json().get("embeddings")
            if not embeddings or len(embeddings) != len(batch):
                raise RagError(
                    f"ollama вернул {len(embeddings or [])} векторов на батч из {len(batch)}"
                )
            vectors.extend(_normalize(v) for v in embeddings)
    return vectors


# --- Индексы по стратегиям ---


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def strategy_path(strategy: str) -> Path:
    return get_settings().rag.output_dir / strategy / "index.json"


def save_index(strategy: str, index: dict) -> Path:
    path = strategy_path(strategy)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_index(strategy: str) -> dict | None:
    path = strategy_path(strategy)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Не удалось прочитать индекс '%s': %s", strategy, exc)
        return None


def list_indexes() -> list[dict]:
    """Сводка по собранным индексам — для UI и быстрой проверки."""
    output_dir = get_settings().rag.output_dir
    known = list(CHUNKERS)
    extra: list[str] = []
    if output_dir.is_dir():
        extra = sorted(
            child.name
            for child in output_dir.iterdir()
            if child.is_dir() and (child / "index.json").is_file() and child.name not in known
        )
    result: list[dict] = []
    for strategy in known + extra:
        index = load_index(strategy)
        if index is None:
            continue
        tokens = [chunk.get("tokens", 0) for chunk in index.get("chunks", [])]
        embedding = index.get("embedding") or {}
        result.append(
            {
                "strategy": strategy,
                "description": index.get("description"),
                "chunks": len(tokens),
                "tokens_min": min(tokens) if tokens else 0,
                "tokens_max": max(tokens) if tokens else 0,
                "tokens_avg": round(sum(tokens) / len(tokens)) if tokens else 0,
                "articles": (index.get("source") or {}).get("articles"),
                "has_embeddings": bool(index.get("vectors")),
                "embedding_model": embedding.get("model"),
                "embedding_dim": embedding.get("dim"),
                "built_at": index.get("built_at"),
                "params": index.get("params"),
            }
        )
    return result


async def build_index(strategy: str, *, embed: bool = True) -> dict:
    """Собирает индекс стратегии: чанки (+ эмбеддинги ollama) -> server/data/rag/<strategy>/."""
    params = get_settings().rag
    if strategy not in CHUNKERS:
        raise RagError(f"Неизвестная стратегия чанкинга: {strategy} (доступны: {', '.join(CHUNKERS)})")
    articles = parse_source(params.source_file)
    chunks, dropped = build_chunks(strategy, articles, params)
    if not chunks:
        raise RagError(f"Стратегия '{strategy}' не дала ни одного чанка")

    index: dict = {
        "strategy": strategy,
        "description": STRATEGIES[strategy],
        "params": {
            "min_tokens": params.min_tokens,
            "max_tokens": params.max_tokens,
            "overlap_tokens": params.overlap_tokens,
            "chars_per_token": params.chars_per_token,
            "min_chunk_tokens": params.min_chunk_tokens,
        },
        "source": {
            "file": str(params.source_file),
            "sha256": _sha256(params.source_file),
            "articles": len(articles),
            "articles_dropped": dropped,
        },
        "embedding": None,
        "vectors": None,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "chunks": chunks,
    }
    if embed:
        vectors = await embed_texts(
            [chunk["text"] for chunk in chunks],
            model=params.embedding_model,
            base_url=params.ollama_base_url,
            batch_size=params.embed_batch_size,
            timeout=params.embed_timeout_sec,
        )
        index["embedding"] = {
            "provider": "ollama",
            "base_url": params.ollama_base_url,
            "model": params.embedding_model,
            "dim": len(vectors[0]),
        }
        index["vectors"] = vectors
    path = save_index(strategy, index)
    logger.info(
        "Индекс '%s': чанков %s (статей %s, отброшено %s), эмбеддинги: %s",
        strategy,
        len(chunks),
        len(articles),
        dropped,
        "да" if index["vectors"] else "нет",
    )
    return index


async def search(query: str, *, strategy: str, top_k: int = 5) -> list[dict]:
    """Косинусный поиск по индексу стратегии (векторы нормализованы — dot product)."""
    index = load_index(strategy)
    if index is None:
        raise RagError(f"Индекс стратегии '{strategy}' не собран (python -m app.rag build)")
    embedding = index.get("embedding") or {}
    vectors = index.get("vectors")
    if not embedding or not vectors:
        raise RagError(f"У индекса '{strategy}' нет эмбеддингов — пересоберите без --no-embed")

    params = get_settings().rag
    query_vector = (
        await embed_texts(
            [query],
            model=embedding["model"],
            base_url=embedding.get("base_url") or params.ollama_base_url,
            batch_size=1,
            timeout=params.embed_timeout_sec,
        )
    )[0]

    scored = [
        (sum(a * b for a, b in zip(query_vector, vector)), i) for i, vector in enumerate(vectors)
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [{**index["chunks"][i], "score": round(score, 4)} for score, i in scored[: max(1, top_k)]]


# --- RAG-чат (вкладка «Чат» при выбранной стратегии) ---


RAG_SYSTEM_PROMPT = (
    "Ты — ассистент по базе знаний pikabu.ru. Отвечай на русском языке, кратко и по делу, "
    "опираясь ИСКЛЮЧИТЕЛЬНО на предоставленный контекст. "
    "Если в контексте нет ответа на вопрос — ответь фразой: "
    "«Ответить на вопрос, опираясь на базу знаний, невозможно. Или переформулируйте вопрос.» "
    "и не выдумывай факты. "
    "Ссылайся на статьи по URL из контекста, когда приводишь факты оттуда. "
    "Когда опираешься на фрагмент контекста, обязательно приведи одну короткую дословную цитату "
    "из него (до ~200 символов, без изменений) отдельной строкой в формате: "
    "> [id_фрагмента] текст цитаты "
    "(id указан в квадратных скобках в начале заголовка фрагмента). "
    "В КОНЦЕ КАЖДОГО ответа всегда выводи раздел «Источники:» — список использованных фрагментов "
    "строками «[id] название — url». Если ответа в контексте нет или контекст не релевантен, "
    "всё равно выведи раздел ровно строкой: "
    "«Источники: не найдены (нет релевантных фрагментов в базе знаний)». "
    "Учитывай состояние задачи диалога (цель, уточнения, ограничения), если оно передано, "
    "и не противоречь ему."
)


def _context_block(hits: list[dict]) -> str:
    """Собирает контекст из найденных чанков для подмешивания в вопрос."""
    blocks: list[str] = []
    for hit in hits:
        metadata = hit.get("metadata") or {}
        header = f"[{hit['id']}] {metadata.get('title') or 'Без названия'}"
        if metadata.get("url"):
            header += f" — {metadata['url']}"
        blocks.append(f"{header}\n{hit.get('text', '')}")
    return "\n\n---\n\n".join(blocks)


def _chunk_hit(hit: dict) -> dict:
    """Чанк в формате для UI: similarity score, reranker score, метаданные и текст."""
    return {
        "id": hit["id"],
        "score": hit["score"],
        "reranker_score": hit.get("reranker_score"),
        "tokens": hit.get("tokens"),
        "metadata": hit.get("metadata") or {},
        "text": hit.get("text", ""),
    }


def _retriever(strategy: str) -> rag_pipeline.Retriever:
    """Замыкает rag.search под сигнатуру, ожидаемую rag_pipeline."""

    async def retrieve(query: str, top_k: int) -> list[dict]:
        return await search(query, strategy=strategy, top_k=top_k)

    return retrieve


def _empty_hits_reply(debug: dict) -> str:
    """Понятный ответ, когда после фильтрации/reranker не осталось фрагментов."""
    counts = debug.get("counts") or {}
    params = debug.get("params") or {}
    retrieved = counts.get("retrieved", 0)
    no_sources = "\n\nИсточники: не найдены (нет релевантных фрагментов в базе знаний)."
    if not retrieved:
        return (
            "По запросу не найдено ни одного фрагмента в индексе. Переформулируйте вопрос."
            + no_sources
        )
    if params.get("reranker_threshold") is not None and counts.get("after_reranker_filter") == 0:
        return (
            f"Reranker отсёк все кандидаты порогом {params['reranker_threshold']} "
            f"({counts.get('after_similarity_filter', 0)} из {retrieved}). "
            "Снизьте reranker threshold или переформулируйте вопрос." + no_sources
        )
    threshold = params.get("similarity_threshold")
    return (
        f"Все найденные фрагменты ({retrieved}) отфильтрованы порогом similarity "
        f"{threshold}. Снизьте similarity threshold или переформулируйте вопрос." + no_sources
    )


async def _rag_context(
    message: str,
    strategy: str,
    history: list[dict],
    options: rag_pipeline.RetrievalOptions | None,
    task_state_data: dict | None,
) -> tuple[list[dict] | None, list[dict], dict]:
    """Общая часть RAG: поиск чанков и сборка сообщений для LLM.

    Возвращает (messages, chunks, debug); messages=None, если релевантных чанков нет.
    """
    params = get_settings().rag
    if options is None:
        hits = await search(message, strategy=strategy, top_k=params.chat_top_k)
        count = len(hits)
        debug = {
            "retrieval_strategy": "baseline",
            "original_query": message,
            "rewritten_query": None,
            "rewrite_fallback": False,
            "reranker_fallback": None,
            "params": {"top_k": params.chat_top_k},
            "counts": {
                "retrieved": count,
                "after_similarity_filter": count,
                "after_reranker_filter": count,
                "final": count,
            },
        }
    else:
        hits, debug = await rag_pipeline.run_retrieval(
            message,
            _retriever(strategy),
            options,
            default_top_k=params.chat_top_k,
            history=history,
            task_state=task_state_data,
        )

    if not hits:
        return None, [], debug

    state_block = task_state.format_for_prompt(task_state_data)
    state_section = f"{state_block}\n\n" if state_block else ""
    user_prompt = (
        f"{state_section}"
        "Контекст из базы знаний (фрагменты статей pikabu):\n\n"
        f"{_context_block(hits)}\n\n"
        f"Вопрос пользователя: {message}"
    )
    messages: list[dict] = [{"role": "system", "content": RAG_SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_prompt})
    return messages, [_chunk_hit(hit) for hit in hits], debug


async def build_rag_reply(
    message: str,
    strategy: str,
    history: list[dict],
    options: rag_pipeline.RetrievalOptions | None = None,
    task_state_data: dict | None = None,
    provider: str = llm.DEFAULT_PROVIDER,
) -> dict:
    """RAG-схема: вопрос → поиск релевантных чанков → объединение с вопросом → LLM → ответ.

    options=None сохраняет прежнее baseline-поведение; иначе выполняется выбранная
    стратегия поиска (query rewrite / similarity filter / reranker) из rag_pipeline.
    task_state_data — память задачи диалога: подмешивается в промпт генерации и
    используется при переформулировке поискового запроса.
    """
    messages, chunks, debug = await _rag_context(
        message, strategy, history, options, task_state_data
    )
    if messages is None:
        return {"reply": _empty_hits_reply(debug), "chunks": [], "debug": debug}
    reply = await llm.complete_messages(messages, provider=provider, phase="rag")
    return {"reply": reply, "chunks": chunks, "debug": debug}


async def build_rag_reply_stream(
    message: str,
    strategy: str,
    history: list[dict],
    options: rag_pipeline.RetrievalOptions | None = None,
    task_state_data: dict | None = None,
    provider: str = llm.DEFAULT_PROVIDER,
):
    """Стрим-вариант `build_rag_reply`: дельты размышлений + финальный результат.

    Генерирует `{"reasoning": str}` по мере генерации и в конце
    `{"done": {reply, chunks, debug, reasoning}}`.
    """
    messages, chunks, debug = await _rag_context(
        message, strategy, history, options, task_state_data
    )
    if messages is None:
        yield {
            "done": {
                "reply": _empty_hits_reply(debug),
                "chunks": [],
                "debug": debug,
                "reasoning": None,
            }
        }
        return
    async for event in llm.stream_complete(messages, provider=provider, phase="rag"):
        if "done" in event:
            result = event["done"]
            yield {
                "done": {
                    "reply": result["content"],
                    "chunks": chunks,
                    "debug": debug,
                    "reasoning": result["reasoning"],
                }
            }
        elif event.get("reasoning"):
            yield {"reasoning": event["reasoning"]}


# --- CLI ---


def _main() -> None:
    parser = argparse.ArgumentParser(
        prog="app.rag",
        description="RAG-пайплайн: чанкинг pikabu-txt.md + эмбеддинги ollama + JSON-индексы",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build_parser = sub.add_parser("build", help="Собрать индексы стратегий чанкинга")
    build_parser.add_argument("--strategy", default="all", choices=[*CHUNKERS, "all"])
    build_parser.add_argument("--no-embed", action="store_true", help="Только чанки, без эмбеддингов")

    sub.add_parser("list", help="Показать собранные индексы")

    search_parser = sub.add_parser("search", help="Поиск по индексу стратегии")
    search_parser.add_argument("query")
    search_parser.add_argument("--strategy", default="fixed", choices=list(CHUNKERS))
    search_parser.add_argument("--top-k", type=int, default=5)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

    if args.command == "build":
        strategies = list(CHUNKERS) if args.strategy == "all" else [args.strategy]
        for strategy in strategies:
            index = asyncio.run(build_index(strategy, embed=not args.no_embed))
            embedding_model = (index.get("embedding") or {}).get("model") or "нет"
            print(
                f"[{strategy}] чанков: {len(index['chunks'])}, "
                f"эмбеддинги: {embedding_model} -> {strategy_path(strategy)}"
            )
    elif args.command == "list":
        for info in list_indexes():
            print(json.dumps(info, ensure_ascii=False))
    elif args.command == "search":
        for hit in asyncio.run(search(args.query, strategy=args.strategy, top_k=args.top_k)):
            meta = hit["metadata"]
            preview = hit["text"][:200].replace("\n", " ")
            print(f"{hit['score']:+.4f}  {hit['id']}  [{meta.get('rating')}] {meta.get('title')}")
            print(f"          {meta.get('url')}")
            print(f"          {preview}…")


if __name__ == "__main__":
    _main()
