<script setup lang="ts">
defineProps<{
  show: boolean
  title: string
  arxivId: string
  formattedDate: string
  isDeleting: boolean
}>()

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()
</script>

<template>
  <Teleport to="body">
    <div
      v-if="show"
      class="fixed inset-0 z-[10000] flex items-center justify-center p-4"
    >
      <!-- Backdrop -->
      <Transition
        appear
        enter-active-class="transition-opacity duration-300 ease-out"
        enter-from-class="opacity-0"
        enter-to-class="opacity-100"
        leave-active-class="transition-opacity duration-200 ease-in"
        leave-from-class="opacity-100"
        leave-to-class="opacity-0"
      >
        <div
          v-if="show"
          class="absolute inset-0 bg-black/40 backdrop-blur-[2px]"
          @click="emit('cancel')"
        ></div>
      </Transition>

      <!-- Modal -->
      <Transition
        appear
        enter-active-class="transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
        enter-from-class="opacity-0 scale-90"
        enter-to-class="opacity-100 scale-100"
        leave-active-class="transition-all duration-200 ease-in"
        leave-from-class="opacity-100 scale-100"
        leave-to-class="opacity-0 scale-95"
      >
        <div
          v-if="show"
          class="relative bg-white rounded-2xl shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)] max-w-md w-full overflow-hidden ring-1 ring-black/5"
          @click.stop
        >
          <!-- Header with gradient accent -->
          <div class="relative px-6 pt-6 pb-5">
            <div class="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-red-500 via-red-400 to-orange-400"></div>
            <div class="flex items-start gap-4">
              <div class="flex-shrink-0 w-12 h-12 rounded-xl bg-gradient-to-br from-red-500 to-red-600 flex items-center justify-center shadow-lg shadow-red-500/25">
                <svg class="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </div>
              <div class="flex-1 min-w-0">
                <h3 class="text-xl font-semibold text-gray-900 tracking-tight">删除论文</h3>
                <p class="text-sm text-gray-500 mt-0.5">此操作无法撤销，请谨慎确认</p>
              </div>
            </div>
          </div>

          <!-- Content -->
          <div class="px-6 pb-5">
            <p class="text-sm text-gray-600 mb-4">确定要删除以下论文吗？</p>
            <div class="p-4 bg-gradient-to-br from-gray-50 to-gray-100/50 rounded-xl border border-gray-200/60">
              <p class="font-display text-[15px] font-medium text-gray-900 leading-snug line-clamp-3">{{ title }}</p>
              <div class="flex items-center gap-2 mt-3">
                <span class="inline-flex items-center px-2 py-0.5 rounded-md bg-white border border-gray-200 text-xs font-mono text-gray-600 shadow-sm">
                  {{ arxivId }}
                </span>
                <span class="text-xs text-gray-400">•</span>
                <span class="text-xs text-gray-500">{{ formattedDate }}</span>
              </div>
            </div>
          </div>

          <!-- Footer -->
          <div class="px-6 py-4 bg-gray-50/80 border-t border-gray-100 flex items-center justify-end gap-3">
            <button
              class="px-5 py-2.5 text-sm font-medium text-gray-600 hover:text-gray-900 hover:bg-white rounded-lg border border-transparent hover:border-gray-200 transition-all duration-150"
              :disabled="isDeleting"
              @click="emit('cancel')"
            >
              取消
            </button>
            <button
              class="px-5 py-2.5 text-sm font-medium text-white bg-gradient-to-r from-red-500 to-red-600 hover:from-red-600 hover:to-red-700 rounded-lg shadow-md shadow-red-500/25 hover:shadow-lg hover:shadow-red-500/30 transition-all duration-150 flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed disabled:shadow-none"
              :disabled="isDeleting"
              @click="emit('confirm')"
            >
              <svg v-if="isDeleting" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span>{{ isDeleting ? '删除中...' : '确认删除' }}</span>
            </button>
          </div>
        </div>
      </Transition>
    </div>
  </Teleport>
</template>
