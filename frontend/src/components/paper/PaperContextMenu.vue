<script setup lang="ts">
defineProps<{
  show: boolean
  position: { x: number; y: number }
  isProcessed: boolean
  isStreaming: boolean
  isRetrying: boolean
  isDeleting: boolean
}>()

const emit = defineEmits<{
  retry: []
  delete: []
  close: []
}>()

function handleRetry() {
  emit('close')
  emit('retry')
}

function handleDelete() {
  emit('close')
  emit('delete')
}
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition duration-100 ease-out"
      enter-from-class="opacity-0 scale-95"
      enter-to-class="opacity-100 scale-100"
      leave-active-class="transition duration-75 ease-in"
      leave-from-class="opacity-100 scale-100"
      leave-to-class="opacity-0 scale-95"
    >
      <div
        v-if="show"
        class="fixed z-[9999] min-w-[160px] bg-white rounded-lg shadow-xl border border-gray-200 py-1 overflow-hidden"
        :style="{ left: `${position.x}px`, top: `${position.y}px` }"
        @click.stop
      >
        <!-- Retry Option -->
        <button
          v-if="!isProcessed"
          class="w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-100 flex items-center gap-2 transition-colors"
          :disabled="isStreaming || isRetrying"
          @click="handleRetry"
        >
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          <span>{{ isStreaming || isRetrying ? '分析中...' : '重新分析' }}</span>
        </button>

        <!-- Divider -->
        <div v-if="!isProcessed" class="border-t border-gray-100 my-1"></div>

        <!-- Delete Option -->
        <button
          class="w-full px-4 py-2 text-left text-sm text-red-600 hover:bg-red-50 flex items-center gap-2 transition-colors"
          :disabled="isDeleting"
          @click="handleDelete"
        >
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
          </svg>
          <span>{{ isDeleting ? '删除中...' : '删除论文' }}</span>
        </button>
      </div>
    </Transition>
  </Teleport>
</template>
