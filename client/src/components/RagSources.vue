<script setup lang="ts">
import { splitHighlighted } from '../citations'
import type { HighlightSegment } from '../citations'
import type { RagChunkHit, RagCitation } from '../types'

const props = withDefaults(defineProps<{ chunks: RagChunkHit[]; citations?: RagCitation[] }>(), {
  citations: () => [],
})

function scoreLabel(score: number): string {
  return score.toFixed(3)
}

function quotedSegments(chunk: RagChunkHit): HighlightSegment[] {
  const quotes = props.citations.filter((item) => item.chunkId === chunk.id).map((item) => item.quote)
  return quotes.length ? splitHighlighted(chunk.text, quotes) : [{ text: chunk.text, highlight: false }]
}
</script>

<template>
  <details class="mt-2 rounded-lg border border-slate-700/70 bg-slate-950/40 px-2.5 py-1.5">
    <summary class="cursor-pointer text-xs font-medium uppercase tracking-wide text-slate-400">
      Источники RAG ({{ chunks.length }})
    </summary>
    <p v-if="!chunks.length" class="mt-2 text-xs text-amber-300/90">
      Источники: релевантные фрагменты в базе знаний не найдены.
    </p>
    <ul class="mt-2 space-y-2">
      <li
        v-for="(chunk, index) in chunks"
        :key="chunk.id"
        class="rounded border border-slate-800 bg-slate-900/60 px-2.5 py-2"
      >
        <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span class="font-mono text-slate-400">#{{ index + 1 }}</span>
          <span class="font-mono text-emerald-300">{{ chunk.id }}</span>
          <span class="font-mono text-indigo-300">similarity {{ scoreLabel(chunk.score) }}</span>
          <span v-if="chunk.reranker_score !== null && chunk.reranker_score !== undefined" class="font-mono text-violet-300">
            reranker {{ scoreLabel(chunk.reranker_score) }}
          </span>
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
          ><template v-for="(segment, segIndex) in quotedSegments(chunk)" :key="segIndex"><mark
              v-if="segment.highlight"
              class="rounded-sm bg-amber-400/25 text-amber-100"
            >{{ segment.text }}</mark><template v-else>{{ segment.text }}</template></template></pre>
        </details>
      </li>
    </ul>
  </details>
</template>
