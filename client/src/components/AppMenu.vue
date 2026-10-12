<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import ChatTabs from './ChatTabs.vue'
import RagSettingsPanel from './RagSettingsPanel.vue'
import { chats, closeMenu, currentChatId, menuOpen, menuTab, setMenuTab } from '../store'

withDefaults(defineProps<{ busy?: boolean }>(), { busy: false })

const emit = defineEmits<{
  (e: 'select', id: string): void
  (e: 'delete', id: string): void
  (e: 'delete-all'): void
  (e: 'new'): void
}>()

function onSelect(id: string) {
  emit('select', id)
  closeMenu()
}

function onNew() {
  emit('new')
  closeMenu()
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && menuOpen.value) closeMenu()
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <Transition name="drawer">
      <div v-if="menuOpen" class="fixed inset-0 z-50 md:hidden">
        <div class="drawer-backdrop absolute inset-0 bg-black/60" @click="closeMenu" />
        <aside
          class="drawer-panel absolute left-0 top-0 flex h-full w-80 max-w-[85vw] flex-col border-r border-slate-800 bg-slate-950 shadow-2xl"
        >
          <div class="flex items-center gap-1 border-b border-slate-800 p-2">
            <button
              type="button"
              class="flex-1 rounded-lg px-3 py-2 text-sm transition"
              :class="menuTab === 'chats' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:bg-slate-800'"
              @click="setMenuTab('chats')"
            >
              Чаты
            </button>
            <button
              type="button"
              class="flex-1 rounded-lg px-3 py-2 text-sm transition"
              :class="menuTab === 'settings' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:bg-slate-800'"
              @click="setMenuTab('settings')"
            >
              Настройки
            </button>
            <button
              type="button"
              class="shrink-0 rounded-lg px-2.5 py-2 text-slate-400 transition hover:bg-slate-800 hover:text-slate-200"
              aria-label="Закрыть меню"
              @click="closeMenu"
            >
              ✕
            </button>
          </div>

          <div class="min-h-0 flex-1 overflow-y-auto">
            <ChatTabs
              v-if="menuTab === 'chats'"
              :chats="chats"
              :current-chat-id="currentChatId"
              :busy="busy"
              @select="onSelect"
              @delete="emit('delete', $event)"
              @delete-all="emit('delete-all')"
              @new="onNew"
            />
            <div v-else class="p-3">
              <RagSettingsPanel />
            </div>
          </div>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.drawer-enter-active,
.drawer-leave-active {
  transition: opacity 0.2s ease;
}
.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}
.drawer-enter-active .drawer-panel,
.drawer-leave-active .drawer-panel {
  transition: transform 0.2s ease;
}
.drawer-enter-from .drawer-panel,
.drawer-leave-to .drawer-panel {
  transform: translateX(-100%);
}
</style>
