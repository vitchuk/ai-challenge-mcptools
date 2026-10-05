# Probe: вопрос без релевантных источников

- Режим: RAG-индекс `fixed`, поиск `similarity-filter` (similarity_threshold=0.99)
- Результат: ✅ сообщение об отсутствии источников выведено

### Пользователь

> Как приготовить классический борщ со свёклой и капустой?

### Ассистент

Все найденные фрагменты (10) отфильтрованы порогом similarity 0.99. Снизьте similarity threshold или переформулируйте вопрос.

Источники: не найдены (нет релевантных фрагментов в базе знаний).

**Найденные источники:** 0

<sub>debug: {"retrieval_strategy": "similarity-filter", "original_query": "Как приготовить классический борщ со свёклой и капустой?", "rewritten_query": null, "rewrite_fallback": false, "reranker_fallback": null, "params": {"top_k": null, "top_k_before": 10, "similarity_threshold": 0.99, "top_k_after": null, "top_k_final": null, "reranker_threshold": null}, "counts": {"retrieved": 10, "after_similarity_filter": 0, "after_reranker_filter": 0, "final": 0}}</sub>
