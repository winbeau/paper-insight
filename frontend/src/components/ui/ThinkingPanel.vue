<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import type { StreamErrorEvent, ProgressStep } from '../../types/paper'

const props = defineProps<{
  steps: ProgressStep[]
  thought: string
  isStreaming: boolean
  error: StreamErrorEvent | null
}>()

const isCollapsed = ref(true)
const contentRef = ref<HTMLElement | null>(null)

const thoughtLines = computed(() => {
  if (!props.thought) return []
  return props.thought.split('\n').filter(line => line.trim())
})

const hasContent = computed(() => {
  return props.thought.length > 0 || props.steps.length > 0
})

const statusIcon = computed(() => {
  if (props.error) return 'error'
  if (props.isStreaming) return 'thinking'
  if (props.thought || props.steps.some(s => s.status === 'done')) return 'done'
  return 'idle'
})

const completedSteps = computed(() => {
  return props.steps.filter(s => s.status === 'done').length
})

// Auto-scroll to bottom when new content arrives
watch(() => props.thought, async () => {
  if (!isCollapsed.value && contentRef.value) {
    await nextTick()
    contentRef.value.scrollTop = contentRef.value.scrollHeight
  }
})

function toggleCollapse() {
  isCollapsed.value = !isCollapsed.value
}
</script>

<template>
  <div
    v-if="hasContent || isStreaming"
    class="thinking-panel rounded-lg border overflow-hidden transition-all duration-200"
    :class="{
      'border-amber-200 bg-amber-50/50': isStreaming && !error,
      'border-red-200 bg-red-50/50': error,
      'border-emerald-200 bg-emerald-50/50': !isStreaming && !error && (thought || steps.length > 0),
      'border-gray-200 bg-gray-50/50': !isStreaming && !error && !thought && steps.length === 0,
    }"
  >
    <!-- Steps Progress Bar -->
    <div v-if="steps.length > 0" class="px-3 pt-3 pb-2">
      <!-- Step Indicators -->
      <div class="flex items-center gap-1 flex-wrap">
        <template v-for="(step, index) in steps" :key="index">
          <!-- Step Item -->
          <div
            class="flex items-center gap-1.5 px-2 py-1 rounded-full text-[10px] font-medium transition-all duration-300 border"
            :class="{
              'bg-emerald-50 text-emerald-700 border-emerald-300': step.status === 'done',
              'bg-amber-50 text-amber-700 border-amber-300 animate-pulse': step.status === 'active',
              'bg-gray-50 text-gray-400 border-gray-200': step.status === 'pending',
              'bg-red-50 text-red-700 border-red-300': step.status === 'error',
            }"
          >
            <!-- Status Icon -->
            <span class="flex-shrink-0">
              <!-- Done -->
              <svg v-if="step.status === 'done'" class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" />
              </svg>
              <!-- Active -->
              <span v-else-if="step.status === 'active'" class="flex h-3 w-3 items-center justify-center">
                <span class="absolute h-2 w-2 rounded-full bg-amber-400 animate-ping"></span>
                <span class="relative h-2 w-2 rounded-full bg-amber-500"></span>
              </span>
              <!-- Pending -->
              <span v-else-if="step.status === 'pending'" class="h-2 w-2 rounded-full bg-gray-300 block"></span>
              <!-- Error -->
              <svg v-else-if="step.status === 'error'" class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </span>
            <!-- Label -->
            <span class="truncate max-w-[80px]">{{ step.label }}</span>
          </div>
          <!-- Connector (except last) -->
          <svg v-if="index < steps.length - 1" class="w-3 h-3 text-gray-300 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
          </svg>
        </template>
      </div>

      <!-- Progress Summary -->
      <div class="mt-2 flex items-center gap-2 text-[10px] text-gray-500">
        <div class="flex-1 h-1 bg-gray-200 rounded-full overflow-hidden">
          <div
            class="h-full rounded-full transition-all duration-500 ease-out"
            :class="{
              'bg-emerald-500': !error && !isStreaming,
              'bg-amber-500': isStreaming && !error,
              'bg-red-500': error,
            }"
            :style="{ width: `${steps.length > 0 ? (completedSteps / steps.length) * 100 : 0}%` }"
          ></div>
        </div>
        <span class="font-mono">{{ completedSteps }}/{{ steps.length }}</span>
      </div>
    </div>

    <!-- Collapsible Header -->
    <button
      v-if="thought || error"
      class="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-black/5 transition-colors border-t"
      :class="{
        'border-amber-100': isStreaming && !error,
        'border-red-100': error,
        'border-emerald-100': !isStreaming && !error && thought,
        'border-gray-100': !isStreaming && !error && !thought,
      }"
      @click="toggleCollapse"
    >
      <div class="flex items-center gap-2">
        <!-- Status Icon -->
        <div class="flex-shrink-0">
          <svg
            v-if="statusIcon === 'thinking'"
            class="w-4 h-4 text-amber-500 animate-pulse"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
            />
          </svg>
          <svg
            v-else-if="statusIcon === 'done'"
            class="w-4 h-4 text-emerald-500"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          <svg
            v-else-if="statusIcon === 'error'"
            class="w-4 h-4 text-red-500"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          <svg
            v-else
            class="w-4 h-4 text-gray-400"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M8 12h.01M12 12h.01M16 12h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
        </div>

        <!-- Title -->
        <span class="text-xs font-medium uppercase tracking-wider"
          :class="{
            'text-amber-700': isStreaming && !error,
            'text-red-700': error,
            'text-emerald-700': !isStreaming && !error && thought,
            'text-gray-500': !isStreaming && !error && !thought,
          }"
        >
          {{ error ? '错误详情' : isStreaming ? 'R1 思考中...' : '思考过程' }}
        </span>
      </div>

      <!-- Collapse Toggle -->
      <svg
        class="w-4 h-4 text-gray-400 transition-transform duration-200"
        :class="{ 'rotate-180': !isCollapsed }"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
      >
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
      </svg>
    </button>

    <!-- Content -->
    <Transition
      enter-active-class="transition-all duration-200 ease-out"
      enter-from-class="max-h-0 opacity-0"
      enter-to-class="max-h-[300px] opacity-100"
      leave-active-class="transition-all duration-150 ease-in"
      leave-from-class="max-h-[300px] opacity-100"
      leave-to-class="max-h-0 opacity-0"
    >
      <div v-if="!isCollapsed && (thought || error)" class="overflow-hidden">
        <div
          ref="contentRef"
          class="px-3 pb-3 max-h-[250px] overflow-y-auto text-xs font-mono leading-relaxed"
          :class="{
            'text-amber-800': isStreaming && !error,
            'text-red-700': error,
            'text-gray-600': !isStreaming && !error,
          }"
        >
          <!-- Error Message -->
          <div v-if="error" class="space-y-1">
            <p class="font-semibold">{{ error.error }}</p>
            <p>{{ error.message }}</p>
          </div>

          <!-- Thought Content -->
          <div v-else-if="thoughtLines.length > 0" class="space-y-1">
            <p v-for="(line, index) in thoughtLines" :key="index">
              {{ line }}
            </p>
          </div>

          <!-- Streaming Indicator -->
          <div v-else-if="isStreaming" class="flex items-center gap-1">
            <span class="w-1.5 h-1.5 rounded-full bg-current animate-bounce" style="animation-delay: 0ms"></span>
            <span class="w-1.5 h-1.5 rounded-full bg-current animate-bounce" style="animation-delay: 150ms"></span>
            <span class="w-1.5 h-1.5 rounded-full bg-current animate-bounce" style="animation-delay: 300ms"></span>
          </div>

          <!-- Empty State -->
          <p v-else class="text-gray-400 italic">
            暂无思考过程
          </p>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.thinking-panel {
  font-family: var(--font-sans, system-ui, sans-serif);
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
}
</style>
