import { computed, watch, onUnmounted, type Ref, type ComputedRef } from 'vue'
import type { StreamErrorEvent, ProgressStep } from '../types/paper'
import { getStreamErrorMessage, parseStoredError } from '../services/api'
import { useProcessingStore } from '../stores/processing'

// While a paper is analyzed elsewhere (scheduler), poll until it finishes
const BACKGROUND_POLL_MS = 5000

export interface StreamProcessingState {
  isStreaming: ComputedRef<boolean>
  isQueued: ComputedRef<boolean>
  streamProgress: ComputedRef<ProgressStep[]>
  streamThought: ComputedRef<string>
  streamError: ComputedRef<StreamErrorEvent | null>
}

export interface StreamProcessingComputed {
  statusValue: ComputedRef<string | null>
  isProcessing: ComputedRef<boolean>
  isFailed: ComputedRef<boolean>
  displayError: ComputedRef<StreamErrorEvent | null>
  statusLabel: ComputedRef<string>
  statusTag: ComputedRef<string>
}

export interface StreamProcessingHandlers {
  handleRetry: () => void
}

/**
 * A paper card's view of its analysis. The run itself lives in the global processing
 * store, so it keeps going when the card is unmounted (tab or filter switch).
 */
export function useStreamProcessing(
  paperId: Ref<number>,
  directionId: Ref<number | null>,
  processingStatus: Ref<string>,
  processingError: Ref<string | null>,
  onRefresh: (paperId: number) => void
): StreamProcessingState & StreamProcessingComputed & StreamProcessingHandlers {
  const store = useProcessingStore()
  const paperRun = computed(() => store.state.runs[paperId.value])

  const isStreaming = computed(() => paperRun.value?.isStreaming ?? false)
  const isQueued = computed(() => store.state.queue.includes(paperId.value))
  const streamProgress = computed(() => paperRun.value?.progress ?? [])
  const streamThought = computed(() => paperRun.value?.thought ?? '')
  const streamError = computed(() => paperRun.value?.error ?? null)

  const statusValue = computed(() => {
    if (isStreaming.value) return 'processing'
    return paperRun.value?.localStatus ?? processingStatus.value
  })
  const isProcessing = computed(() => statusValue.value === 'processing')
  const isFailed = computed(() => statusValue.value === 'failed')

  // Error from the live stream, else the one stored by the last failed run
  const displayError = computed<StreamErrorEvent | null>(() => {
    if (streamError.value) return streamError.value
    if (isFailed.value) return parseStoredError(processingError.value)
    return null
  })

  const statusLabel = computed(() => {
    // Step details live in the progress panel; don't repeat them here
    if (isStreaming.value) return '分析中...'
    if (isQueued.value) return '排队等待分析'
    if (statusValue.value === 'processing') return '后台分析中...'
    if (statusValue.value === 'failed') {
      return displayError.value ? getStreamErrorMessage(displayError.value) : '分析失败'
    }
    return '等待分析'
  })

  const statusTag = computed(() => {
    if (isStreaming.value) return 'streaming'
    if (isQueued.value) return 'queued'
    if (statusValue.value === 'processing') return 'processing'
    if (statusValue.value === 'failed') return 'failed'
    return 'pending'
  })

  // Poll the paper while the backend processes it without a stream of ours
  let pollTimer: ReturnType<typeof setInterval> | null = null
  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }
  watch(
    () => isProcessing.value && !isStreaming.value,
    (backgroundRun) => {
      stopPolling()
      if (backgroundRun) pollTimer = setInterval(() => onRefresh(paperId.value), BACKGROUND_POLL_MS)
    },
    { immediate: true }
  )

  // A refreshed status from the server supersedes a stale local one
  watch(processingStatus, (newStatus) => {
    const r = paperRun.value
    if (r && !r.isStreaming && r.localStatus === 'processing' && newStatus !== 'processing') {
      r.localStatus = null
      r.progress = []
    }
  })

  function handleRetry() {
    store.analyzeNow(paperId.value, directionId.value)
  }

  onUnmounted(stopPolling)

  return {
    isStreaming,
    isQueued,
    streamProgress,
    streamThought,
    streamError,
    statusValue,
    isProcessing,
    isFailed,
    displayError,
    statusLabel,
    statusTag,
    handleRetry,
  }
}
