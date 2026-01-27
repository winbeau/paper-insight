import { ref, computed, watch, onUnmounted, type Ref, type ComputedRef } from 'vue'
import type { DifyAnalysisResult, StreamErrorEvent, ProgressStep } from '../types/paper'
import { processPaperStream, getStreamErrorMessage } from '../services/api'

// Pre-defined workflow steps with parallel groups
// Steps with same group number are displayed in parallel
export const WORKFLOW_STEPS: Array<{ label: string; group?: number }> = [
  { label: '下载PDF' },
  { label: '上传文件' },
  { label: '用户输入' },
  { label: 'Parse File', group: 1 },
  { label: '知识检索', group: 1 },
  { label: 'LLM' },
  { label: '整合输出' },
]

export interface StreamProcessingState {
  isStreaming: Ref<boolean>
  isRetrying: Ref<boolean>
  streamProgress: Ref<ProgressStep[]>
  streamThought: Ref<string>
  streamError: Ref<StreamErrorEvent | null>
  streamResult: Ref<DifyAnalysisResult | null>
  localStatus: Ref<string | null>
}

export interface StreamProcessingComputed {
  statusValue: ComputedRef<string | null>
  isProcessing: ComputedRef<boolean>
  isFailed: ComputedRef<boolean>
  statusLabel: ComputedRef<string>
  statusTag: ComputedRef<string>
}

export interface StreamProcessingHandlers {
  handleRetry: () => void
}

export function useStreamProcessing(
  paperId: Ref<number>,
  processingStatus: Ref<string>,
  _isProcessed: Ref<boolean>,
  onRefresh: () => void
): StreamProcessingState & StreamProcessingComputed & StreamProcessingHandlers {
  // State
  const isStreaming = ref(false)
  const isRetrying = ref(false)
  const streamProgress = ref<ProgressStep[]>([])
  const streamThought = ref('')
  const streamError = ref<StreamErrorEvent | null>(null)
  const streamResult = ref<DifyAnalysisResult | null>(null)
  const localStatus = ref<string | null>(null)
  let streamAbortFn: (() => void) | null = null

  // Computed
  const statusValue = computed(() => {
    return localStatus.value ?? processingStatus.value
  })

  const isProcessing = computed(() => {
    return statusValue.value === 'processing'
  })

  const isFailed = computed(() => {
    return statusValue.value === 'failed'
  })

  const statusLabel = computed(() => {
    if (isStreaming.value || statusValue.value === 'processing') return 'Dify 分析中...'
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

  // Watch for paper status changes (e.g., batch processing started after page load)
  watch(
    () => processingStatus.value,
    (newStatus, oldStatus) => {
      // Clear progress when processing completes or fails (and we weren't streaming)
      if (newStatus !== 'processing' && oldStatus === 'processing' && !isStreaming.value) {
        streamProgress.value = []
      }
    }
  )

  // Map progress event to step update
  function handleProgressEvent(event: { status: string; message: string }) {
    if (event.status === 'started') {
      // Initialize all steps as pending, first one active
      streamProgress.value = WORKFLOW_STEPS.map((step, index) => ({
        label: step.label,
        status: index === 0 ? 'active' : 'pending',
        group: step.group,
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
        // Mark all previous non-grouped steps as done (but not parallel ones that might still be running)
        for (let i = 0; i < stepIndex; i++) {
          if (steps[i].group === undefined) {
            steps[i].status = 'done'
          }
        }
        // Mark current step as active
        steps[stepIndex].status = 'active'
        // If this step has a group, also activate parallel steps in the same group
        const currentGroup = steps[stepIndex].group
        if (currentGroup !== undefined) {
          steps.forEach((s) => {
            if (s.group === currentGroup && s.status === 'pending') {
              s.status = 'active'
            }
          })
        }
      } else {
        // If node name doesn't match, just mark previous active as done and find next pending
        const prevActive = steps.findIndex(s => s.status === 'active')
        if (prevActive >= 0) {
          // Mark all active steps as done (including parallel ones)
          steps.forEach(s => {
            if (s.status === 'active') {
              s.status = 'done'
            }
          })
          // Activate next pending step
          const nextPending = steps.findIndex(s => s.status === 'pending')
          if (nextPending >= 0) {
            steps[nextPending].status = 'active'
            // If next step has a group, also activate parallel steps
            const nextGroup = steps[nextPending].group
            if (nextGroup !== undefined) {
              steps.forEach((s) => {
                if (s.group === nextGroup && s.status === 'pending') {
                  s.status = 'active'
                }
              })
            }
          }
        }
      }

      streamProgress.value = [...steps]
    } else if (event.status === 'node_finished') {
      // Extract node name and mark only that specific step as done
      const match = event.message.match(/完成节点:\s*(.+)/)
      const nodeName = match ? match[1] : event.message

      const steps = streamProgress.value
      const stepIndex = steps.findIndex(s => s.label === nodeName)

      if (stepIndex >= 0) {
        // Mark only this specific step as done (allows parallel steps to complete independently)
        steps[stepIndex].status = 'done'

        // Check if all steps in the same parallel group are done
        const currentGroup = steps[stepIndex].group
        if (currentGroup !== undefined) {
          const groupSteps = steps.filter(s => s.group === currentGroup)
          const allGroupDone = groupSteps.every(s => s.status === 'done')

          // If all parallel steps are done, activate the next non-grouped step
          if (allGroupDone) {
            const nextPending = steps.findIndex(s => s.status === 'pending' && s.group === undefined)
            if (nextPending >= 0) {
              steps[nextPending].status = 'active'
            }
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

    const { abort } = processPaperStream(paperId.value, {
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
        onRefresh()
      },
    })

    streamAbortFn = abort
  }

  // Cleanup on unmount
  onUnmounted(() => {
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
    statusLabel,
    statusTag,
    // Handlers
    handleRetry,
  }
}
