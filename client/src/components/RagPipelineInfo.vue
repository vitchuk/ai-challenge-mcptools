<script setup lang="ts">
import type { RagPipelineDebug } from '../types'

defineProps<{ debug: RagPipelineDebug }>()

function formatParam(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : String(value)
}
</script>

<template>
  <details class="mt-2 rounded-lg border border-slate-700/70 bg-slate-950/40 px-2.5 py-1.5">
    <summary class="cursor-pointer text-xs font-medium uppercase tracking-wide text-slate-400">
      RAG-пайплайн · {{ debug.retrieval_strategy }}
    </summary>
    <div class="mt-2 space-y-1.5 text-xs">
      <p class="text-slate-400">
        Original query: <span class="text-slate-200">{{ debug.original_query }}</span>
      </p>
      <p v-if="debug.rewritten_query" class="text-slate-400">
        Rewritten query: <span class="text-indigo-200">{{ debug.rewritten_query }}</span>
      </p>
      <div
        class="rounded border border-slate-800 bg-slate-900/60 px-2 py-1.5 font-mono text-[11px] text-slate-300"
      >
        vector search: {{ debug.counts.retrieved }}
        → similarity filter: {{ debug.counts.after_similarity_filter }}
        → reranker: {{ debug.counts.after_reranker_filter }}
        → final: {{ debug.counts.final }}
      </div>
      <p v-if="debug.rewrite_fallback" class="text-amber-300">
        Query rewrite не удался — использован исходный запрос.
      </p>
      <p v-if="debug.reranker_fallback" class="text-amber-300">
        Reranker недоступен — сохранён порядок similarity.
      </p>
      <p class="text-slate-500">
        top_k: {{ formatParam(debug.params.top_k) }} ·
        top_k_before: {{ formatParam(debug.params.top_k_before) }} ·
        similarity: {{ formatParam(debug.params.similarity_threshold) }} ·
        top_k_after: {{ formatParam(debug.params.top_k_after) }} ·
        top_k_final: {{ formatParam(debug.params.top_k_final) }}
        <template v-if="debug.params.reranker_threshold !== null && debug.params.reranker_threshold !== undefined">
          · reranker: {{ formatParam(debug.params.reranker_threshold) }}
        </template>
      </p>
    </div>
  </details>
</template>
