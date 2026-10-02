<script setup lang="ts">
import type { RagChunkHit } from '../types'

defineProps<{ chunks: RagChunkHit[] }>()

function scoreLabel(score: number): string {
  return score.toFixed(3)
}
</script>

<template>
  <details class="mt-2 rounded-lg border border-slate-700/70 bg-slate-950/40 px-2.5 py-1.5">
    <summary class="cursor-pointer text-xs font-medium uppercase tracking-wide text-slate-400">
      Источники RAG ({{ chunks.length }})
    </summary>
    <ul class="mt-2 space-y-2">
      <li
        v-for="chunk in chunks"
        :key="chunk.id"
        class="rounded border border-slate-800 bg-slate-900/60 px-2.5 py-2"
      >
        <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span class="font-mono text-emerald-300">{{ chunk.id }}</span>
          <span class="font-mono text-indigo-300">score {{ scoreLabel(chunk.score) }}</span>
          <span v-if="chunk.tokens" class="text-slate-500">~{{ chunk.tokens }} токенов</span>
        </div>
        <p class="mt-1 text-xs text-slate-200">
          <a
            v-if="chunk.metadata.url"
            :href="chunk.metadata.url"
            target="_blank"
            rel="noreferrer"
            class="underline decoration-dotted hover:text-indigo-300"
          >
            {{ chunk.metadata.title || chunk.metadata.url }}
          </a>
          <span v-else>{{ chunk.metadata.title || 'Без названия' }}</span>
        </p>
        <p class="mt-0.5 text-[11px] text-slate-500">
          {{ chunk.metadata.author || 'автор неизвестен' }}
          <span v-if="chunk.metadata.rating !== null"> · рейтинг {{ chunk.metadata.rating }}</span>
          <span v-if="chunk.metadata.date"> · {{ chunk.metadata.date }}</span>
        </p>
        <details class="mt-1">
          <summary class="cursor-pointer text-[11px] text-slate-400 hover:text-slate-300">
            текст чанка
          </summary>
          <pre
            class="mt-1 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-slate-950/70 p-2 text-[11px] leading-relaxed text-slate-300"
          >{{ chunk.text }}</pre>
        </details>
      </li>
    </ul>
  </details>
</template>
