<script setup lang="ts">
import type { Post } from '../types'

const props = defineProps<{ post: Post }>()

function formatDate(iso: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <article class="rounded-lg border border-slate-800 bg-slate-900/70 p-3 transition hover:border-slate-700">
    <a
      :href="props.post.url"
      target="_blank"
      rel="noopener noreferrer"
      class="text-sm font-medium text-indigo-300 hover:text-indigo-200"
    >
      {{ props.post.title }}
    </a>
    <div class="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-400">
      <span v-if="props.post.author">{{ props.post.author }}</span>
      <span v-if="props.post.theme" class="text-slate-500">{{ props.post.theme }}</span>
      <span v-if="props.post.rating !== null">рейтинг: {{ props.post.rating }}</span>
      <span v-if="props.post.comments_count !== null">комментариев: {{ props.post.comments_count }}</span>
      <span v-if="props.post.published_at">{{ formatDate(props.post.published_at) }}</span>
    </div>
    <p v-if="props.post.body_text" class="mt-2 line-clamp-3 text-xs leading-relaxed text-slate-300">
      {{ props.post.body_text }}
    </p>
    <div v-if="props.post.images.length" class="mt-2 flex gap-2">
      <img
        v-for="(image, index) in props.post.images.slice(0, 4)"
        :key="index"
        :src="image"
        alt=""
        loading="lazy"
        class="h-14 w-14 rounded object-cover"
      />
    </div>
    <div v-if="props.post.videos.length" class="mt-1 text-xs text-slate-400">
      видео: {{ props.post.videos.length }}
    </div>
  </article>
</template>
