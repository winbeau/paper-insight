import { ref, computed, watch, onUnmounted, type Ref, type ComputedRef } from 'vue'
import type { AnalysisResult, StreamErrorEvent, ProgressStep } from '../types/paper'
import { processPaperStream, getStreamErrorMessage, parseStoredError } from '../services/api'

// While a paper is analyzed elsewhere (scheduler, another card), poll until it finishes
const BACKGROUND_POLL_MS = 5000

export interface StreamProcessingState {
  isStreaming: Ref<boolean>
  isRetrying: Ref<boolean>
  streamProgress: Ref<ProgressStep[]>
  streamThought: Ref<string>
  streamError: Ref<StreamErrorEvent | null>
  streamResult: Ref<AnalysisResult | null>
  localStatus: Ref<string | null>
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

export function useStreamProcessing(
  paperId: Ref<number>,
  processingStatus: Ref<string>,
  processingError: Ref<string | null>,
  onRefresh: (paperId: number) => void
): StreamProcessingState & StreamProcessingComputed & StreamProcessingHandlers {
  // State
  const isStreaming = ref(false)
  const isRetrying = ref(false)
  const streamProgress = ref<ProgressStep[]>([])
  const streamThought = ref('')
  const streamError = ref<StreamErrorEvent | null>(null)
  const streamResult = ref<AnalysisResult | null>(null)
  const localStatus = ref<string | null>(null)
  let streamAbortFn: (() => void) | null = null
  let pollTimer: ReturnType<typeof setInterval> | null = null

  // Computed
  const statusValue = computed(() => localStatus.value ?? processingStatus.value)
  const isProcessing = computed(() => statusValue.value === 'processing')
  const isFailed = computed(() => statusValue.value === 'failed')

  // Error from the live stream, else the one stored by the last failed run
  const displayError = computed<StreamErrorEvent | null>(() => {
    if (streamError.value) return streamError.value
    if (isFailed.value) return parseStoredError(processingError.value)
    return null
  })

  const statusLabel = computed(() => {
    if (isStreaming.value) {
      const active = streamProgress.value.find(s => s.status === 'active')
      return active?.message || active?.label || '分析中...'
    }
    if (statusValue.value === 'processing') return '后台分析中...'
    if (statusValue.value === 'failed') {
      return displayError.value ? getStreamErrorMessage(displayError.value) : '分析失败'
    }
    return '等待分析'
  })

  const statusTag = computed(() => {
    if (isStreaming.value) return 'streaming'
    if (statusValue.value === 'processing') return 'processing'
    if (statusValue.value === 'failed') return 'failed'
    return 'pending'
  })

  // Poll the paper while someone else is processing it, so the card updates when done
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
      if (backgroundRun) {
        pollTimer = setInterval(() => onRefresh(paperId.value), BACKGROUND_POLL_MS)
      }
    },
    { immediate: true }
  )

  // A refreshed paper status supersedes the local one (e.g. background run finished)
  watch(
    () => processingStatus.value,
    (newStatus, oldStatus) => {
      if (isStreaming.value) return
      if (localStatus.value === 'processing' && newStatus !== 'processing') localStatus.value = null
      if (newStatus !== 'processing' && oldStatus === 'processing') streamProgress.value = []
    }
  )

  function updateStep(key: string, status: ProgressStep['status'], message?: string) {
    streamProgress.value = streamProgress.value.map(step =>
      step.key === key
        ? { ...step, status, message: message || step.message }
        : step
    )
  }

  async function handleRetry() {
    // Allow retry even if DB status is "processing" (the backend answers 'busy' if it really is)
    if (isRetrying.value || isStreaming.value) return

    isRetrying.value = true
    isStreaming.value = true
    localStatus.value = 'processing'
    streamProgress.value = []
    streamThought.value = ''
    streamError.value = null
    streamResult.value = null

    const { abort } = processPaperStream(paperId.value, {
      onStarted: (event) => {
        streamProgress.value = event.steps.map(step => ({ ...step, status: 'pending' as const }))
      },
      onProgress: (event) => {
        if (event.status === 'step_started') updateStep(event.step, 'active', event.message)
        else if (event.status === 'step_progress') updateStep(event.step, 'active', event.message)
        else if (event.status === 'step_finished') updateStep(event.step, 'done', event.message)
        else if (event.status === 'step_skipped') updateStep(event.step, 'skipped', event.message)
      },
      onThinking: (_chunk, accumulated) => {
        streamThought.value = accumulated
      },
      onResult: (result) => {
        streamResult.value = result
        streamProgress.value = streamProgress.value.map(s =>
          s.status === 'skipped' ? s : { ...s, status: 'done' as const }
        )
      },
      onError: (error) => {
        isStreaming.value = false
        isRetrying.value = false
        if (error.error === 'busy') {
          // Someone else owns this run: show it as processing and poll for the outcome
          streamProgress.value = []
          localStatus.value = 'processing'
          return
        }
        streamError.value = error
        streamProgress.value = streamProgress.value.map(s =>
          s.status === 'active' ? { ...s, status: 'error' as const } : s
        )
        localStatus.value = 'failed'
      },
      onDone: () => {
        isStreaming.value = false
        isRetrying.value = false
        localStatus.value = null
        onRefresh(paperId.value)
      },
    })

    streamAbortFn = abort
  }

  onUnmounted(() => {
    stopPolling()
    if (streamAbortFn) {
      streamAbortFn()
      streamAbortFn = null
    }
  })

  return {
    // State
    isStreaming,
    isRetrying,
    streamProgress,
    streamThought,
    streamError,
    streamResult,
    localStatus,
    // Computed
    statusValue,
    isProcessing,
    isFailed,
    displayError,
    statusLabel,
    statusTag,
    // Handlers
    handleRetry,
  }
}
