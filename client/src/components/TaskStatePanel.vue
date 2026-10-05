<script setup lang="ts">
import type { TaskState } from '../types'

defineProps<{ state: TaskState }>()
</script>

<template>
  <details
    open
    class="mt-2 rounded-lg border border-emerald-700/50 bg-emerald-950/20 px-2.5 py-1.5"
  >
    <summary class="cursor-pointer text-xs font-medium uppercase tracking-wide text-emerald-300/80">
      Память задачи
    </summary>
    <div class="mt-2 space-y-2 text-xs">
      <div v-if="state.goal">
        <p class="font-medium text-emerald-200">Цель диалога</p>
        <p class="text-slate-200">{{ state.goal }}</p>
      </div>
      <div v-if="state.clarifications.length">
        <p class="font-medium text-emerald-200">Уточнения пользователя</p>
        <ul class="list-disc space-y-0.5 pl-4 text-slate-200">
          <li v-for="(item, index) in state.clarifications" :key="index">{{ item }}</li>
        </ul>
      </div>
      <div v-if="state.constraints.length">
        <p class="font-medium text-emerald-200">Ограничения и термины</p>
        <ul class="list-disc space-y-0.5 pl-4 text-slate-200">
          <li v-for="(item, index) in state.constraints" :key="index">{{ item }}</li>
        </ul>
      </div>
      <p v-if="!state.goal && !state.clarifications.length && !state.constraints.length" class="text-slate-500">
        Пока пусто — сделайте несколько уточнений в диалоге.
      </p>
    </div>
  </details>
</template>
