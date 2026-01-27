<script setup lang="ts">
import { ref, computed, toRef, watch, onMounted, onUnmounted } from 'vue'
import type { Paper } from '../../types/paper'
import RelevanceBadge from '../ui/RelevanceBadge.vue'
import HeuristicBox from '../ui/HeuristicBox.vue'
import ThinkingPanel from '../ui/ThinkingPanel.vue'
import ThumbnailPreview from './ThumbnailPreview.vue'
import PaperContextMenu from './PaperContextMenu.vue'
import DeleteConfirmModal from './DeleteConfirmModal.vue'
import { useThumbnailPreview } from '../../composables/useThumbnailPreview'
import { useStreamProcessing } from '../../composables/useStreamProcessing'
import { deletePaper } from '../../services/api'

const props = defineProps<{
  paper: Paper
  autoProcess?: boolean  // When true, automatically start processing
}>()

const emit = defineEmits<{
  refresh: []
  delete: [id: number]
  'processing-done': [id: number, success: boolean]  // Emitted when auto-processing completes
}>()

// Card expansion state
const isExpanded = ref(false)
const abstractRef = ref<HTMLElement | null>(null)

// Context menu state
const showContextMenu = ref(false)
const contextMenuPosition = ref({ x: 0, y: 0 })

// Delete state
const isDeleting = ref(false)
const showDeleteConfirm = ref(false)

// Thumbnail preview composable
const thumbnailUrl = computed(() => props.paper.thumbnail_url)
const {
  isHoveringAbstract,
  thumbnailStyle,
  previewOrigin,
  handleMouseEnter,
  handleMouseMove,
  handleMouseLeave,
} = useThumbnailPreview(thumbnailUrl, abstractRef)

// Stream processing composable
const {
  isStreaming,
  isRetrying,
  streamProgress,
  streamThought,
  streamError,
  isProcessing,
  isFailed,
  statusLabel,
  statusTag,
  handleRetry,
} = useStreamProcessing(
  toRef(() => props.paper.id),
  toRef(() => props.paper.processing_status),
  toRef(() => props.paper.is_processed),
  () => emit('refresh')
)

// Auto-process when autoProcess prop becomes true
watch(
  () => props.autoProcess,
  (shouldProcess) => {
    if (shouldProcess && !props.paper.is_processed && !isStreaming.value && !isRetrying.value) {
      handleRetry()
    }
  },
  { immediate: true }
)

// Emit processing-done when streaming completes (for batch processing coordination)
watch(isStreaming, (streaming, wasStreaming) => {
  if (wasStreaming && !streaming && props.autoProcess) {
    // Stream just finished, emit completion status
    const success = !streamError.value && !isFailed.value
    emit('processing-done', props.paper.id, success)
  }
})

// Computed helpers
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

// Lifecycle
onMounted(() => {
  document.addEventListener('click', closeContextMenu)
})

onUnmounted(() => {
  document.removeEventListener('click', closeContextMenu)
})

// Context menu handlers
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

// Delete handlers
function handleDeleteRequest() {
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

function toggleExpand() {
  isExpanded.value = !isExpanded.value
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
    <PaperContextMenu
      :show="showContextMenu"
      :position="contextMenuPosition"
      :is-processed="paper.is_processed"
      :is-streaming="isStreaming"
      :is-retrying="isRetrying"
      :is-deleting="isDeleting"
      @retry="handleRetry"
      @delete="handleDeleteRequest"
      @close="closeContextMenu"
    />

    <!-- Delete Confirmation Modal -->
    <DeleteConfirmModal
      :show="showDeleteConfirm"
      :title="paper.title"
      :arxiv-id="paper.arxiv_id"
      :formatted-date="formattedDate"
      :is-deleting="isDeleting"
      @confirm="confirmDelete"
      @cancel="cancelDelete"
    />

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

              <ThumbnailPreview
                :show="isHoveringAbstract"
                :thumbnail-url="paper.thumbnail_url || ''"
                :style="thumbnailStyle"
                :origin="previewOrigin"
              />
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
