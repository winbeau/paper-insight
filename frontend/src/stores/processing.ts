/**
 * Global analysis queue and streams.
 *
 * Analyses used to live inside PaperCard components, so switching the feed (direction
 * tab, filters) unmounted the card and aborted its run. They now live here: one queue
 * and one set of concurrency slots shared by all research directions, independent of
 * what is on screen. Cards only read their paper's state.
 */
import { reactive } from 'vue'
import type { AnalysisResult, ProgressStep, StreamErrorEvent } from '../types/paper'
import { prepareBatch, processPaperStream, stopAllProcessing } from '../services/api'
import { getLogger } from '../utils/logger'

const logger = getLogger('processing')

export const MAX_CONCURRENT = 3

export interface PaperRun {
  isStreaming: boolean
  progress: ProgressStep[]
  thought: string
  error: StreamErrorEvent | null
  result: AnalysisResult | null
  /** 'processing' while the backend owns the run, 'failed' after an error, null otherwise */
  localStatus: string | null
  directionId: number | null
}

interface State {
  runs: Record<number, PaperRun>
  queue: number[]            // paper ids waiting for a slot (all directions)
  running: number[]          // paper ids with an open stream
  stopping: boolean
}

const state = reactive<State>({ runs: {}, queue: [], running: [], stopping: false })
const aborters = new Map<number, () => void>()
const changeListeners = new Set<(paperId: number) => void>()

function run(paperId: number): PaperRun {
  if (!state.runs[paperId]) {
    state.runs[paperId] = {
      isStreaming: false, progress: [], thought: '', error: null, result: null, localStatus: null, directionId: null,
    }
  }
  return state.runs[paperId]
}

function notifyChanged(paperId: number) {
  for (const listener of changeListeners) listener(paperId)
}

function updateStep(paperId: number, key: string, status: ProgressStep['status'], message?: string) {
  const r = run(paperId)
  r.progress = r.progress.map(step =>
    step.key === key
      ? {
          ...step,
          status,
          message: message || step.message,
          startedAt: status === 'active' ? (step.startedAt ?? Date.now()) : step.startedAt,
        }
      : step,
  )
}

function finish(paperId: number) {
  aborters.delete(paperId)
  state.running = state.running.filter(id => id !== paperId)
  pump()
}

function resetRun(paperId: number) {
  const r = run(paperId)
  r.isStreaming = false
  r.progress = []
  r.thought = ''
  r.error = null
  r.localStatus = null
}

function start(paperId: number) {
  const r = run(paperId)
  state.running = [...state.running, paperId]
  r.isStreaming = true
  r.localStatus = 'processing'
  r.progress = []
  r.thought = ''
  r.error = null
  r.result = null

  const { abort } = processPaperStream(paperId, {
    onStarted: (event) => {
      r.progress = event.steps.map(step => ({ ...step, status: 'pending' as const }))
    },
    onProgress: (event) => {
      if (event.status === 'step_started' || event.status === 'step_progress') updateStep(paperId, event.step, 'active', event.message)
      else if (event.status === 'step_finished') updateStep(paperId, event.step, 'done', event.message)
      else if (event.status === 'step_skipped') updateStep(paperId, event.step, 'skipped', event.message)
    },
    onThinking: (_chunk, accumulated) => {
      r.thought = accumulated
    },
    onResult: (result) => {
      r.result = result
      r.progress = r.progress.map(s => (s.status === 'skipped' ? s : { ...s, status: 'done' as const }))
    },
    onError: (error) => {
      r.isStreaming = false
      if (error.error === 'stopped') {
        resetRun(paperId)
      } else if (error.error === 'busy') {
        // Someone else (e.g. the scheduler) owns this run: show it as processing
        r.progress = []
        r.localStatus = 'processing'
      } else {
        r.error = error
        r.progress = r.progress.map(s => (s.status === 'active' ? { ...s, status: 'error' as const } : s))
        r.localStatus = 'failed'
      }
      finish(paperId)
      notifyChanged(paperId)
    },
    onDone: () => {
      r.isStreaming = false
      r.localStatus = null
      finish(paperId)
      notifyChanged(paperId)
    },
  })
  aborters.set(paperId, abort)
}

function pump() {
  while (state.running.length < MAX_CONCURRENT && state.queue.length > 0) {
    const next = state.queue.shift()!
    if (!state.running.includes(next)) start(next)
  }
}

export function useProcessingStore() {
  return {
    state,

    runFor(paperId: number): PaperRun | undefined {
      return state.runs[paperId]
    },

    isQueued(paperId: number): boolean {
      return state.queue.includes(paperId)
    },

    get active(): boolean {
      return state.running.length > 0 || state.queue.length > 0
    },

    /** Directions with something running or queued (for the feed tabs' indicator). */
    activeDirections(): Set<number> {
      const ids = new Set<number>()
      for (const paperId of [...state.running, ...state.queue]) {
        const directionId = state.runs[paperId]?.directionId
        if (directionId != null) ids.add(directionId)
      }
      return ids
    },

    /** Queue papers (any direction) and start MinerU on all of them right away. */
    enqueue(paperIds: number[], directionId: number | null) {
      const fresh = paperIds.filter(id => !state.running.includes(id) && !state.queue.includes(id))
      if (fresh.length === 0) return
      for (const id of fresh) run(id).directionId = directionId
      prepareBatch(fresh).catch(e => logger.warn('Parse prefetch failed', e))
      state.queue.push(...fresh)
      pump()
    },

    /** Analyze one paper next (e.g. the card's analyze / retry button). */
    analyzeNow(paperId: number, directionId: number | null) {
      if (state.running.includes(paperId)) return
      run(paperId).directionId = directionId
      state.queue = [paperId, ...state.queue.filter(id => id !== paperId)]
      pump()
    },

    /** Stop everything: queued papers, open streams and backend runs (scheduler too). */
    async stopAll() {
      if (state.stopping) return
      state.stopping = true
      state.queue = []
      try {
        await stopAllProcessing()
      } catch (e) {
        logger.error('Failed to stop processing', e)
      }
      // Streams normally end with a 'stopped' event; drop any that are still open
      for (const [paperId, abort] of aborters) {
        abort()
        resetRun(paperId)
      }
      aborters.clear()
      state.running = []
      state.stopping = false
    },

    /** Papers were deleted: drop them from the queue and forget their state. */
    forget(paperIds: number[]) {
      const gone = new Set(paperIds)
      state.queue = state.queue.filter(id => !gone.has(id))
      for (const id of paperIds) {
        if (!state.running.includes(id)) delete state.runs[id]
      }
    },

    onPaperChanged(listener: (paperId: number) => void): () => void {
      changeListeners.add(listener)
      return () => changeListeners.delete(listener)
    },
  }
}
