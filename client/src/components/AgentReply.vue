<script setup lang="ts">
import { computed } from 'vue'
import { linkifyText, shortLinkLabel } from '../links'
import type { Post } from '../types'

const props = defineProps<{ text: string; posts: Record<string, Post> }>()

interface Segment {
  text: string
  bold?: boolean
  href?: string
}

interface Block {
  kind: 'text' | 'post' | 'space'
  segments?: Segment[]
  title?: string
  href?: string
  meta?: string
  mediaImage?: string | null
  mediaVideo?: boolean
}

const STORY_LINK_RE = /\[([^\]]+)\]\((https?:\/\/pikabu\.ru\/story\/[^\s)]+)\)/
const INLINE_RE = /\[([^\]]+)\]\(([^)\s]+)\)|\*\*([^*]+)\*\*/g

function parseInline(text: string): Segment[] {
  const segments: Segment[] = []
  const pushPlain = (plain: string) => {
    for (const part of linkifyText(plain)) segments.push(part)
  }
  let lastIndex = 0
  let match: RegExpExecArray | null
  INLINE_RE.lastIndex = 0
  while ((match = INLINE_RE.exec(text)) !== null) {
    if (match.index > lastIndex) {
      pushPlain(text.slice(lastIndex, match.index))
    }
    if (match[1] !== undefined && match[2] !== undefined) {
      segments.push({ text: shortLinkLabel(match[2], match[1]), href: match[2] })
    } else if (match[3] !== undefined) {
      segments.push({ text: match[3], bold: true })
    }
    lastIndex = INLINE_RE.lastIndex
  }
  if (lastIndex < text.length) {
    pushPlain(text.slice(lastIndex))
  }
  return segments.filter((segment) => segment.text.length > 0)
}

function cleanMeta(line: string, titleMatch: RegExpExecArray | null): string {
  let meta = line
  if (titleMatch) meta = meta.replace(titleMatch[0], ' ')
  meta = meta.replace(/\[[^\]]*\]\([^)]*\)/g, ' ')
  meta = meta.replace(/\*\*/g, ' ')
  meta = meta.replace(/[·•]/g, ' · ')
  meta = meta.replace(/(·\s*){2,}/g, '· ')
  meta = meta.replace(/\s{2,}/g, ' ')
  return meta.replace(/^[\s·—–-]+/, '').replace(/[\s·—–-]+$/, '').trim()
}

const blocks = computed<Block[]>(() => {
  const result: Block[] = []
  for (const raw of props.text.split('\n')) {
    const line = raw.trim()
    if (!line) {
      result.push({ kind: 'space' })
      continue
    }
    const storyMatch = STORY_LINK_RE.exec(line)
    if (storyMatch) {
      const href = storyMatch[2]
      const boldMatch = /\*\*([^*]+)\*\*/.exec(line)
      const post = props.posts[href]
      const image = post?.images?.[0] ?? null
      result.push({
        kind: 'post',
        title: shortLinkLabel(href, boldMatch ? boldMatch[1] : storyMatch[1]),
        href,
        meta: cleanMeta(line, boldMatch),
        mediaImage: image,
        mediaVideo: image === null && (post?.videos?.length ?? 0) > 0,
      })
    } else {
      result.push({ kind: 'text', segments: parseInline(line) })
    }
  }
  return result
})
</script>

<template>
  <div class="space-y-1">
    <template v-for="(block, index) in blocks" :key="index">
      <div v-if="block.kind === 'space'" class="h-2" />

      <p v-else-if="block.kind === 'text'" class="text-sm leading-relaxed text-slate-100">
        <template v-for="(segment, segIndex) in block.segments" :key="segIndex">
          <a
            v-if="segment.href"
            :href="segment.href"
            target="_blank"
            rel="noopener noreferrer"
            class="inline-flex items-center gap-1 align-middle text-indigo-300 underline decoration-dotted underline-offset-2 hover:text-indigo-200"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              aria-hidden="true"
              class="h-3 w-3 shrink-0"
            >
              <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
              <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
            </svg>
            <span>{{ segment.text }}</span>
          </a>
          <strong v-else-if="segment.bold" class="font-semibold text-slate-100">{{ segment.text }}</strong>
          <span v-else>{{ segment.text }}</span>
        </template>
      </p>

      <div v-else class="rounded-lg border border-slate-800 bg-slate-900/60 p-2">
        <a
          :href="block.href"
          target="_blank"
          rel="noopener noreferrer"
          class="text-sm font-medium text-indigo-300 hover:text-indigo-200"
        >
          {{ block.title }}
        </a>
        <a
          v-if="block.mediaImage"
          :href="block.href"
          target="_blank"
          rel="noopener noreferrer"
          class="mt-2 block"
        >
          <img :src="block.mediaImage" alt="" loading="lazy" class="max-h-48 w-full rounded object-cover" />
        </a>
        <a
          v-else-if="block.mediaVideo"
          :href="block.href"
          target="_blank"
          rel="noopener noreferrer"
          class="mt-2 flex h-20 items-center justify-center rounded bg-slate-800 text-slate-400"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" class="h-7 w-7" fill="none" stroke="currentColor" stroke-width="1.5" aria-label="Видео" role="img">
            <circle cx="12" cy="12" r="9" />
            <path d="M10 8.5l6 3.5-6 3.5z" fill="currentColor" stroke="none" />
          </svg>
        </a>
        <p v-if="block.meta" class="mt-1 text-xs text-slate-400">{{ block.meta }}</p>
      </div>
    </template>
  </div>
</template>
