<script setup lang="ts">
import { ref, computed } from 'vue'
import type { Paper } from '../../types/paper'
import RelevanceBadge from '../ui/RelevanceBadge.vue'
import HeuristicBox from '../ui/HeuristicBox.vue'
import { processPaper } from '../../services/api'

const props = defineProps<{
  paper: Paper
}>()

const emit = defineEmits<{
  refresh: []
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
  if (statusValue.value === 'processing') return 'DeepSeek reasoning...'
  if (statusValue.value === 'failed') return 'Analysis failed'
  return 'Queued for analysis'
})

const statusTag = computed(() => {
  if (statusValue.value === 'processing') return 'processing'
  if (statusValue.value === 'failed') return 'failed'
  return 'pending'
})

async function handleRetry() {
  if (isRetrying.value || isProcessing.value) return
  isRetrying.value = true
  localStatus.value = 'processing'
  try {
    await processPaper(props.paper.id)
    localStatus.value = null
    emit('refresh')
  } catch (error) {
    localStatus.value = 'failed'
    console.error('Retry failed:', error)
  } finally {
    isRetrying.value = false
  }
}

function toggleExpand() {
  isExpanded.value = !isExpanded.value
}

function calculatePreviewPosition(event: MouseEvent) {
  if (!props.paper.thumbnail_url) return

  const thumbWidth = 400 // Matches w-[400px]
  const thumbHeight = 500 // Estimate
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
    class="bg-[var(--color-paper-100)] rounded-xl border border-[var(--color-paper-200)] transition-all duration-200 cursor-pointer"
    :class="[
      isExpanded
        ? 'shadow-[var(--shadow-card-hover)]'
        : 'shadow-[var(--shadow-card)] hover:shadow-[var(--shadow-card-hover)] hover:-translate-y-0.5'
    ]"
    @click="toggleExpand"
  >
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
                      <!-- Gradient overlay for depth -->
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
          <span class="text-[var(--color-paper-300)]">•</span>
          <div class="flex gap-1">
            <span
              v-for="cat in categoriesList"
              :key="cat"
              class="px-1.5 py-0.5 bg-[var(--color-paper-200)] rounded text-xs"
            >
              {{ cat }}
            </span>
          </div>
          <span class="text-[var(--color-paper-300)]">•</span>
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
      class="px-5 py-3 bg-[var(--color-paper-200)] rounded-b-xl border-t border-[var(--color-paper-300)]"
    >
      <div class="flex items-center justify-between text-xs text-[var(--color-ink-400)]">
        <span class="flex items-center gap-2">
          <svg
            v-if="isProcessing"
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
            v-if="isFailed"
            class="px-2 py-0.5 rounded-full text-[10px] font-medium uppercase tracking-wider text-[var(--color-ink-700)] bg-[var(--color-paper-100)] border border-[var(--color-paper-300)] hover:bg-[var(--color-paper-50)] transition-colors"
            @click.stop="handleRetry"
            :disabled="isRetrying"
          >
            {{ isRetrying ? 'retrying' : 'retry' }}
          </button>
        </div>
      </div>
      <div v-if="isProcessing" class="relative mt-2 h-1.5 w-full overflow-hidden rounded-full bg-[var(--color-paper-300)]">
        <div class="absolute inset-y-0 left-0 w-1/3 bg-[var(--color-ink-700)]/60 animate-progress-bar"></div>
      </div>
    </div>
  </article>
</template>
