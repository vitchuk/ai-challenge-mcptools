<script setup lang="ts">
import { computed } from 'vue'
import type { Post } from '../types'

const props = defineProps<{ post: Post }>()

const image = computed<string | null>(() => props.post.images?.[0] ?? null)
const hasVideo = computed<boolean>(() => (props.post.videos?.length ?? 0) > 0)
const hasMedia = computed<boolean>(() => image.value !== null || hasVideo.value)

function formatDate(iso: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
</script>

<template>
  <article class="overflow-hidden rounded-lg border border-slate-800 bg-slate-900/70 transition hover:border-slate-700">
    <div class="p-3 pb-0">
      <a
        :href="props.post.url"
        target="_blank"
        rel="noopener noreferrer"
        class="text-sm font-medium text-indigo-300 hover:text-indigo-200"
      >
        {{ props.post.title }}
      </a>
    </div>

    <a v-if="hasMedia" :href="props.post.url" target="_blank" rel="noopener noreferrer" class="mt-2 block">
      <img v-if="image" :src="image" alt="" loading="lazy" class="h-44 w-full object-cover" />
      <div
        v-else
        role="img"
        aria-label="Видео"
        class="flex h-24 w-full items-center justify-center bg-slate-800 text-slate-400"
      >
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" class="h-9 w-9" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="9" />
          <path d="M10 8.5l6 3.5-6 3.5z" fill="currentColor" stroke="none" />
        </svg>
      </div>
    </a>

    <p v-if="props.post.body_text" class="line-clamp-3 px-3 pt-2 text-xs leading-relaxed text-slate-300">
      {{ props.post.body_text }}
    </p>

    <div class="flex items-center justify-between gap-2 px-3 py-2 text-xs text-slate-400">
      <span>
        <span v-if="props.post.rating !== null">рейтинг: {{ props.post.rating }}</span>
        <span v-if="props.post.rating !== null && props.post.comments_count !== null">, </span>
        <span v-if="props.post.comments_count !== null">комментариев: {{ props.post.comments_count }}</span>
      </span>
      <span v-if="props.post.published_at">{{ formatDate(props.post.published_at) }}</span>
    </div>
  </article>
</template>
