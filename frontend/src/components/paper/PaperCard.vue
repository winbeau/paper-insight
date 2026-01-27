<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import type { Paper, DifyAnalysisResult, StreamErrorEvent, ProgressStep } from '../../types/paper'
import RelevanceBadge from '../ui/RelevanceBadge.vue'
import HeuristicBox from '../ui/HeuristicBox.vue'
import ThinkingPanel from '../ui/ThinkingPanel.vue'
import { processPaperStream, getStreamErrorMessage, deletePaper } from '../../services/api'

const props = defineProps<{
  paper: Paper
}>()

const emit = defineEmits<{
  refresh: []
  delete: [id: number]
}>()

const isExpanded = ref(false)
const isHoveringAbstract = ref(false)
const isRetrying = ref(false)
const localStatus = ref<string | null>(null)
const abstractRef = ref<HTMLElement | null>(null)
const thumbnailStyle = ref({
  left: '0px',
  top: '0px',
})
const previewOrigin = ref('origin-left')
const pendingPreviewStyle = ref<{ left: string; top: string } | null>(null)
const pendingPreviewOrigin = ref<string | null>(null)
let reappearTimer: number | null = null

// Streaming state
const isStreaming = ref(false)
const streamProgress = ref<ProgressStep[]>([])
const streamThought = ref('')
const streamError = ref<StreamErrorEvent | null>(null)
const streamResult = ref<DifyAnalysisResult | null>(null)
let streamAbortFn: (() => void) | null = null

// Context menu state
const showContextMenu = ref(false)
const contextMenuPosition = ref({ x: 0, y: 0 })
const isDeleting = ref(false)
const showDeleteConfirm = ref(false)

const formattedDate = computed(() => {
  const date = new Date(props.paper.published)
  const now = new Date()
  const diffDays = Math.floor((now.getTime() - date.getTime()) / (1000 * 60 * 60 * 24))

  if (diffDays === 0) return 'Today'
  if (diffDays === 1) return 'Yesterday'
  if (diffDays < 7) return `${diffDays} days ago`

  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined,
  })
})

const authorsList = computed(() => {
  const authors = props.paper.authors.split(',').map(a => a.trim())
  if (authors.length <= 2) return authors.join(', ')
  return `${authors[0]} et al.`
})

const categoriesList = computed(() => {
  return props.paper.categories.split(',').map(c => c.trim()).slice(0, 3)
})

const statusValue = computed(() => {
  return localStatus.value ?? props.paper.processing_status
})

const isProcessing = computed(() => {
  return statusValue.value === 'processing'
})

const isFailed = computed(() => {
  return statusValue.value === 'failed'
})

const statusLabel = computed(() => {
  if (isStreaming.value) return 'Dify 分析中...'
  if (statusValue.value === 'processing') return 'Processing...'
  if (statusValue.value === 'failed') return streamError.value
    ? getStreamErrorMessage(streamError.value)
    : 'Analysis failed'
  return 'Queued for analysis'
})

const statusTag = computed(() => {
  if (isStreaming.value) return 'streaming'
  if (statusValue.value === 'processing') return 'processing'
  if (statusValue.value === 'failed') return 'failed'
  return 'pending'
})

// Cleanup on unmount
onUnmounted(() => {
  if (streamAbortFn) {
    streamAbortFn()
    streamAbortFn = null
  }
  document.removeEventListener('click', closeContextMenu)
})

// Close context menu on click outside
onMounted(() => {
  document.addEventListener('click', closeContextMenu)
})

function closeContextMenu() {
  showContextMenu.value = false
}

function handleContextMenu(event: MouseEvent) {
  event.preventDefault()
  showContextMenu.value = true
  contextMenuPosition.value = {
    x: event.clientX,
    y: event.clientY,
  }
}

async function handleDelete() {
  if (isDeleting.value) return
  showContextMenu.value = false
  showDeleteConfirm.value = true
}

async function confirmDelete() {
  isDeleting.value = true
  try {
    await deletePaper(props.paper.id)
    emit('delete', props.paper.id)
  } catch (error) {
    console.error('Failed to delete paper:', error)
  } finally {
    isDeleting.value = false
    showDeleteConfirm.value = false
  }
}

function cancelDelete() {
  showDeleteConfirm.value = false
}

function handleContextRetry() {
  showContextMenu.value = false
  handleRetry()
}

// Pre-defined workflow steps
const WORKFLOW_STEPS = [
  '下载 PDF',
  '上传文件',
  '用户输入',
  '知识检索',
  'LLM',
  '整合输出',
]

// Map progress event to step update
function handleProgressEvent(event: { status: string; message: string }) {
  if (event.status === 'started') {
    // Initialize all steps as pending, first one active
    streamProgress.value = WORKFLOW_STEPS.map((label, index) => ({
      label,
      status: index === 0 ? 'active' : 'pending',
    })) as ProgressStep[]
  } else if (event.status === 'workflow_started') {
    // Mark first two steps as done
    const steps = streamProgress.value
    if (steps.length >= 2) {
      steps[0].status = 'done'
      steps[1].status = 'done'
    }
    streamProgress.value = [...steps]
  } else if (event.status === 'node_started') {
    // Extract node name
    const match = event.message.match(/执行节点:\s*(.+)/)
    const nodeName = match ? match[1] : event.message

    // Find and update the matching step
    const steps = streamProgress.value
    const stepIndex = steps.findIndex(s => s.label === nodeName)

    if (stepIndex >= 0) {
      // Mark all previous steps as done
      for (let i = 0; i < stepIndex; i++) {
        steps[i].status = 'done'
      }
      // Mark current step as active
      steps[stepIndex].status = 'active'
    } else {
      // If node name doesn't match, just mark previous active as done and find next pending
      const prevActive = steps.findIndex(s => s.status === 'active')
      if (prevActive >= 0) {
        steps[prevActive].status = 'done'
        // Activate next pending step
        const nextPending = steps.findIndex(s => s.status === 'pending')
        if (nextPending >= 0) {
          steps[nextPending].status = 'active'
        }
      }
    }

    streamProgress.value = [...steps]
  }
}

async function handleRetry() {
  if (isRetrying.value || isProcessing.value || isStreaming.value) return

  isRetrying.value = true
  isStreaming.value = true
  localStatus.value = 'processing'
  streamProgress.value = []
  streamThought.value = ''
  streamError.value = null
  streamResult.value = null

  const { abort } = processPaperStream(props.paper.id, {
    onProgress: (event) => {
      handleProgressEvent(event)
    },
    onThinking: (_chunk, accumulated) => {
      streamThought.value = accumulated
    },
    onResult: (result) => {
      streamResult.value = result
      // Mark all steps done
      streamProgress.value = streamProgress.value.map(s => ({ ...s, status: 'done' as const }))
    },
    onError: (error) => {
      streamError.value = error
      // Mark active step as error
      streamProgress.value = streamProgress.value.map(s =>
        s.status === 'active' ? { ...s, status: 'error' as const } : s
      )
      localStatus.value = 'failed'
      isStreaming.value = false
      isRetrying.value = false
    },
    onDone: () => {
      isStreaming.value = false
      isRetrying.value = false
      localStatus.value = null
      emit('refresh')
    },
  })

  streamAbortFn = abort
}

function toggleExpand() {
  isExpanded.value = !isExpanded.value
}

function calculatePreviewPosition(event: MouseEvent) {
  if (!props.paper.thumbnail_url) return

  const thumbWidth = 400
  const thumbHeight = 500
  const padding = 16
  const offset = 20
  const viewportWidth = window.innerWidth
  const viewportHeight = window.innerHeight

  let newLeft = event.clientX + offset
  let newTop = event.clientY + offset
  let origin = 'origin-left'

  if (newLeft + thumbWidth + padding > viewportWidth) {
    newLeft = event.clientX - thumbWidth - offset
    origin = 'origin-right'
    if (newLeft < padding) {
      newLeft = padding
    }
  }

  if (newTop + thumbHeight + padding > viewportHeight) {
    newTop = event.clientY - thumbHeight - offset
  }

  newTop = Math.max(padding, Math.min(newTop, viewportHeight - thumbHeight - padding))

  return {
    style: {
      left: `${newLeft}px`,
      top: `${newTop}px`,
    },
    origin,
  }
}

function updatePreviewPosition(event: MouseEvent) {
  const result = calculatePreviewPosition(event)
  if (!result) return
  thumbnailStyle.value = result.style
  previewOrigin.value = result.origin
}


function handleMouseEnter(event: MouseEvent) {
  if (!abstractRef.value || !props.paper.thumbnail_url) return
  if (reappearTimer !== null) {
    window.clearTimeout(reappearTimer)
    reappearTimer = null
  }
  updatePreviewPosition(event)
  isHoveringAbstract.value = true
}

function handleMouseLeave() {
  if (reappearTimer !== null) {
    window.clearTimeout(reappearTimer)
    reappearTimer = null
  }
  pendingPreviewStyle.value = null
  pendingPreviewOrigin.value = null
  isHoveringAbstract.value = false
}

function handleMouseMove(event: MouseEvent) {
  if (!props.paper.thumbnail_url) return

  const result = calculatePreviewPosition(event)
  if (!result) return

  const nextStyle = result.style
  const origin = result.origin

  if (!isHoveringAbstract.value) {
    pendingPreviewStyle.value = nextStyle
    pendingPreviewOrigin.value = origin
    if (reappearTimer === null) {
      reappearTimer = window.setTimeout(() => {
        if (pendingPreviewStyle.value && pendingPreviewOrigin.value) {
          thumbnailStyle.value = pendingPreviewStyle.value
          previewOrigin.value = pendingPreviewOrigin.value
        }
        pendingPreviewStyle.value = null
        pendingPreviewOrigin.value = null
        isHoveringAbstract.value = true
        reappearTimer = null
      }, 200)
    }
    return
  }

  if (origin !== previewOrigin.value) {
    pendingPreviewStyle.value = nextStyle
    pendingPreviewOrigin.value = origin
    isHoveringAbstract.value = false
    if (reappearTimer === null) {
      reappearTimer = window.setTimeout(() => {
        if (pendingPreviewStyle.value && pendingPreviewOrigin.value) {
          thumbnailStyle.value = pendingPreviewStyle.value
          previewOrigin.value = pendingPreviewOrigin.value
        }
        pendingPreviewStyle.value = null
        pendingPreviewOrigin.value = null
        isHoveringAbstract.value = true
        reappearTimer = null
      }, 200)
    }
    return
  }

  thumbnailStyle.value = nextStyle
  previewOrigin.value = origin
}
</script>

<template>
  <article
    class="bg-[var(--color-paper-100)] rounded-xl border border-[var(--color-paper-200)] transition-all duration-200 cursor-pointer relative"
    :class="[
      isExpanded
        ? 'shadow-[var(--shadow-card-hover)]'
        : 'shadow-[var(--shadow-card)] hover:shadow-[var(--shadow-card-hover)] hover:-translate-y-0.5'
    ]"
    @click="toggleExpand"
    @contextmenu="handleContextMenu"
  >
    <!-- Context Menu -->
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
          v-if="showContextMenu"
          class="fixed z-[9999] min-w-[160px] bg-white rounded-lg shadow-xl border border-gray-200 py-1 overflow-hidden"
          :style="{ left: `${contextMenuPosition.x}px`, top: `${contextMenuPosition.y}px` }"
          @click.stop
        >
          <!-- Retry Option -->
          <button
            v-if="!paper.is_processed"
            class="w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-100 flex items-center gap-2 transition-colors"
            :disabled="isStreaming || isRetrying"
            @click="handleContextRetry"
          >
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            <span>{{ isStreaming || isRetrying ? '分析中...' : '重新分析' }}</span>
          </button>

          <!-- Divider -->
          <div v-if="!paper.is_processed" class="border-t border-gray-100 my-1"></div>

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

    <!-- Delete Confirmation Modal -->
    <Teleport to="body">
      <Transition
        enter-active-class="transition duration-200 ease-out"
        enter-from-class="opacity-0"
        enter-to-class="opacity-100"
        leave-active-class="transition duration-150 ease-in"
        leave-from-class="opacity-100"
        leave-to-class="opacity-0"
      >
        <div
          v-if="showDeleteConfirm"
          class="fixed inset-0 z-[10000] flex items-center justify-center p-4"
          @click.self="cancelDelete"
        >
          <!-- Backdrop -->
          <div class="absolute inset-0 bg-black/50 backdrop-blur-sm"></div>

          <!-- Modal -->
          <Transition
            enter-active-class="transition duration-200 ease-out"
            enter-from-class="opacity-0 scale-95 translate-y-4"
            enter-to-class="opacity-100 scale-100 translate-y-0"
            leave-active-class="transition duration-150 ease-in"
            leave-from-class="opacity-100 scale-100 translate-y-0"
            leave-to-class="opacity-0 scale-95 translate-y-4"
          >
            <div
              v-if="showDeleteConfirm"
              class="relative bg-white rounded-xl shadow-2xl max-w-md w-full overflow-hidden"
              @click.stop
            >
              <!-- Header -->
              <div class="px-6 pt-6 pb-4">
                <div class="flex items-center gap-3">
                  <div class="flex-shrink-0 w-10 h-10 rounded-full bg-red-100 flex items-center justify-center">
                    <svg class="w-5 h-5 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </div>
                  <div>
                    <h3 class="text-lg font-semibold text-gray-900">删除论文</h3>
                    <p class="text-sm text-gray-500">此操作无法撤销</p>
                  </div>
                </div>
              </div>

              <!-- Content -->
              <div class="px-6 pb-4">
                <p class="text-sm text-gray-600 mb-3">确定要删除以下论文吗？</p>
                <div class="p-3 bg-gray-50 rounded-lg border border-gray-100">
                  <p class="text-sm font-medium text-gray-900 line-clamp-2">{{ paper.title }}</p>
                  <p class="text-xs text-gray-500 mt-1">{{ paper.arxiv_id }}</p>
                </div>
              </div>

              <!-- Footer -->
              <div class="px-6 py-4 bg-gray-50 border-t border-gray-100 flex items-center justify-end gap-3">
                <button
                  class="px-4 py-2 text-sm font-medium text-gray-700 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
                  :disabled="isDeleting"
                  @click="cancelDelete"
                >
                  取消
                </button>
                <button
                  class="px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 rounded-lg transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                  :disabled="isDeleting"
                  @click="confirmDelete"
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
      </Transition>
    </Teleport>

    <div class="p-5">
      <!-- Header -->
      <div class="flex items-start gap-3 mb-3">
        <RelevanceBadge :score="paper.relevance_score" />
        <h2 class="font-display text-lg font-semibold text-[var(--color-ink-900)] leading-snug flex-1">
          {{ paper.title }}
        </h2>
        <button
          v-if="isExpanded"
          @click.stop="isExpanded = false"
          class="flex-shrink-0 p-1 rounded-lg hover:bg-[var(--color-paper-200)] text-[var(--color-ink-400)] transition-colors"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <!-- Heuristic Idea (Focal Point) -->
      <HeuristicBox :content="paper.heuristic_idea" class="mb-4" />

      <!-- Expanded Content -->
      <Transition name="card-expand">
        <div v-if="isExpanded" class="space-y-4 mb-4 animate-fade-in">
          <!-- Chinese Summary -->
          <div v-if="paper.summary_zh">
            <h3 class="text-xs font-semibold uppercase tracking-wider text-[var(--color-ink-400)] mb-2">
              Summary (中文)
            </h3>
            <p class="text-[var(--color-ink-700)] text-sm leading-relaxed">
              {{ paper.summary_zh }}
            </p>
          </div>

          <!-- Abstract -->
          <div>
            <h3 class="text-xs font-semibold uppercase tracking-wider text-[var(--color-ink-400)] mb-2">
              Abstract
            </h3>
            <div
              ref="abstractRef"
              class="relative group"
              @mouseenter="handleMouseEnter"
              @mousemove="handleMouseMove"
              @mouseleave="handleMouseLeave"
            >
              <p class="text-[var(--color-ink-700)] text-sm leading-relaxed cursor-help">
                {{ paper.abstract }}
              </p>

              <Teleport to="body">
                <Transition
                  :enter-active-class="`transition duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] transform ${previewOrigin}`"
                  enter-from-class="opacity-0 scale-90 translate-y-2 translate-x-[-10px]"
                  enter-to-class="opacity-100 scale-100 translate-y-0 translate-x-0"
                  :leave-active-class="`transition duration-200 ease-in transform ${previewOrigin}`"
                  leave-from-class="opacity-100 scale-100 translate-y-0"
                  leave-to-class="opacity-0 scale-95 translate-y-2"
                >
                  <div
                    v-if="isHoveringAbstract && paper.thumbnail_url"
                    class="fixed z-[9999] pointer-events-none shadow-2xl rounded-lg border-2 border-white bg-white w-[400px] ring-1 ring-black/5 flex flex-col"
                    :style="thumbnailStyle"
                  >
                    <div class="w-full relative bg-gray-50 rounded-t-lg overflow-hidden">
                      <img
                        :src="paper.thumbnail_url"
                        class="w-full h-auto object-contain block"
                        alt="Paper Preview"
                      />
                      <div class="absolute inset-0 bg-gradient-to-t from-black/5 to-transparent pointer-events-none mix-blend-multiply"></div>
                    </div>

                    <div class="bg-white px-3 py-2 flex items-center justify-between border-t border-gray-100 rounded-b-lg">
                      <span class="text-[10px] font-bold text-gray-400 uppercase tracking-wider">First Page Preview</span>
                      <span class="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse"></span>
                    </div>
                  </div>
                </Transition>
              </Teleport>
            </div>
          </div>

          <!-- Relevance Reason -->
          <div v-if="paper.relevance_reason">
            <h3 class="text-xs font-semibold uppercase tracking-wider text-[var(--color-ink-400)] mb-2">
              Relevance Analysis
            </h3>
            <p class="text-[var(--color-ink-700)] text-sm leading-relaxed">
              {{ paper.relevance_reason }}
            </p>
          </div>
        </div>
      </Transition>

      <!-- Footer Meta -->
      <div class="flex items-center justify-between pt-3 border-t border-[var(--color-paper-200)]">
        <div class="flex items-center gap-2 text-sm text-[var(--color-ink-400)]">
          <span>{{ authorsList }}</span>
          <span class="text-[var(--color-paper-300)]">&middot;</span>
          <div class="flex gap-1">
            <span
              v-for="cat in categoriesList"
              :key="cat"
              class="px-1.5 py-0.5 bg-[var(--color-paper-200)] rounded text-xs"
            >
              {{ cat }}
            </span>
          </div>
          <span class="text-[var(--color-paper-300)]">&middot;</span>
          <span>{{ formattedDate }}</span>
        </div>

        <a
          v-if="isExpanded"
          :href="paper.pdf_url"
          target="_blank"
          rel="noopener noreferrer"
          @click.stop
          class="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--color-ink-900)] text-white text-sm font-medium rounded-lg hover:bg-[var(--color-ink-700)] transition-colors"
        >
          View PDF
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
          </svg>
        </a>
      </div>
    </div>

    <!-- Processing Status -->
    <div
      v-if="!paper.is_processed"
      class="px-5 py-3 bg-[var(--color-paper-200)]/60 rounded-b-xl border-t border-[var(--color-paper-300)]/50"
    >
      <!-- Dify Workflow Progress -->
      <ThinkingPanel
        v-if="isStreaming || streamProgress.length > 0 || streamError"
        :steps="streamProgress"
        :thought="streamThought"
        :is-streaming="isStreaming"
        :error="streamError"
        class="mb-3"
        @click.stop
      />

      <div class="flex items-center justify-between text-xs text-[var(--color-ink-400)]">
        <span class="flex items-center gap-2">
          <svg
            v-if="isProcessing || isStreaming"
            class="w-3.5 h-3.5 animate-spin"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          {{ statusLabel }}
        </span>
        <div class="flex items-center gap-2">
          <span class="font-mono text-[10px] uppercase tracking-wider">
            {{ statusTag }}
          </span>
          <button
            v-if="isFailed && !isStreaming"
            class="px-2 py-0.5 rounded-full text-[10px] font-medium uppercase tracking-wider text-[var(--color-ink-700)] bg-[var(--color-paper-100)] border border-[var(--color-paper-300)] hover:bg-[var(--color-paper-50)] transition-colors"
            @click.stop="handleRetry"
            :disabled="isRetrying"
          >
            {{ isRetrying ? 'retrying' : 'retry' }}
          </button>
          <button
            v-if="!isFailed && !isStreaming && !isProcessing"
            class="px-2 py-0.5 rounded-full text-[10px] font-medium uppercase tracking-wider text-[var(--color-ink-700)] bg-[var(--color-paper-100)] border border-[var(--color-paper-300)] hover:bg-[var(--color-paper-50)] transition-colors"
            @click.stop="handleRetry"
            :disabled="isRetrying"
          >
            analyze
          </button>
        </div>
      </div>
    </div>
  </article>
</template>
