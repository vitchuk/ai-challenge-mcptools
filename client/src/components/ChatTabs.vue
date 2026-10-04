<script setup lang="ts">
import type { ChatInfo } from '../types'

withDefaults(
  defineProps<{ chats: ChatInfo[]; currentChatId: string | null; busy?: boolean }>(),
  { busy: false },
)

const emit = defineEmits<{
  (e: 'select', id: string): void
  (e: 'delete', id: string): void
  (e: 'new'): void
}>()
</script>

<template>
  <div class="flex h-full flex-col">
    <div class="flex items-center justify-between gap-2 border-b border-slate-800 px-3 py-2">
      <span class="text-xs font-medium uppercase tracking-wide text-slate-400">Чаты ({{ chats.length }})</span>
      <button
        type="button"
        :disabled="busy"
        class="rounded-lg border border-slate-700 px-2 py-1 text-xs text-slate-200 transition hover:border-indigo-500 hover:text-indigo-300 disabled:opacity-40"
        @click="emit('new')"
      >
        + Новый чат
      </button>
    </div>

    <p v-if="!chats.length" class="px-3 py-4 text-xs text-slate-500">
      Чатов пока нет — начните новый.
    </p>

    <ul class="flex-1 space-y-1 overflow-y-auto p-2">
      <li v-for="chat in chats" :key="chat.session_id">
        <div
          class="group flex items-start gap-1 rounded-lg border px-2 py-1.5 transition"
          :class="chat.session_id === currentChatId
            ? 'border-indigo-500/60 bg-indigo-950/40'
            : 'border-transparent hover:border-slate-700 hover:bg-slate-900/60'"
        >
          <button
            type="button"
            :disabled="busy"
            class="min-w-0 flex-1 text-left disabled:opacity-60"
            :title="chat.title"
            @click="emit('select', chat.session_id)"
          >
            <p
              class="line-clamp-2 text-xs leading-snug"
              :class="chat.session_id === currentChatId ? 'text-indigo-100' : 'text-slate-300'"
            >
              {{ chat.title }}
            </p>
            <p class="mt-0.5 text-[10px] text-slate-500">{{ chat.messages_count }} сообщ.</p>
          </button>
          <button
            type="button"
            :disabled="busy"
            class="shrink-0 rounded px-1 text-sm leading-none text-slate-500 transition hover:text-red-400 disabled:opacity-40"
            title="Удалить чат"
            aria-label="Удалить чат"
            @click.stop="emit('delete', chat.session_id)"
          >
            ✕
          </button>
        </div>
      </li>
    </ul>
  </div>
</template>
