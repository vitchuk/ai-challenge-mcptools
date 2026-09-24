<script setup lang="ts">
import type { ToolCallEvent } from '../types'

const props = defineProps<{ calls: ToolCallEvent[] }>()

function argsPreview(args: Record<string, unknown>): string {
  const keys = Object.keys(args)
  if (!keys.length) return ''
  return JSON.stringify(args)
}
</script>

<template>
  <div v-if="props.calls.length" class="mb-2 flex flex-wrap gap-2">
    <details
      v-for="(call, index) in props.calls"
      :key="index"
      class="group rounded-md border border-slate-700 bg-slate-950/60 text-xs"
    >
      <summary class="cursor-pointer select-none px-2 py-1 font-mono text-emerald-300">
        tool: {{ call.name }}<span v-if="argsPreview(call.arguments)" class="text-slate-400"> {{ argsPreview(call.arguments) }}</span>
      </summary>
      <pre class="max-h-48 overflow-auto whitespace-pre-wrap break-words px-2 py-1 text-slate-400">{{ call.result_preview }}</pre>
    </details>
  </div>
</template>
