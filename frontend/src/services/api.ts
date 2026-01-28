import axios from 'axios'
import type {
  Paper,
  Stats,
  AppSettings,
  DifyAnalysisResult,
  StreamProgressEvent,
  StreamThinkingEvent,
  StreamAnswerEvent,
  StreamErrorEvent,
  StreamEventType,
} from '../types/paper'
import { getLogger } from '../utils/logger'

const logger = getLogger('api')

const baseURL = import.meta.env.VITE_API_BASE_URL || '/paper-insight/api'

export const api = axios.create({
  baseURL,
  timeout: 30000,
})

// --- Request / Response logging interceptors ---
api.interceptors.request.use(
  (config) => {
    logger.debug(`${config.method?.toUpperCase()} ${config.baseURL}${config.url}`, config.params ?? '')
    return config
  },
  (error) => {
    logger.error('Request error', error)
    return Promise.reject(error)
  },
)

api.interceptors.response.use(
  (response) => {
    logger.debug(`${response.status} ${response.config.url}`)
    return response
  },
  (error) => {
    if (axios.isAxiosError(error)) {
      logger.error(
        `${error.response?.status ?? 'NETWORK'} ${error.config?.url ?? '?'}: ${error.message}`,
      )
    } else {
      logger.error('Unexpected error', error)
    }
    return Promise.reject(error)
  },
)

export async function fetchPapers(params?: {
  skip?: number
  limit?: number
  min_score?: number
  processed_only?: boolean
}): Promise<Paper[]> {
  const { data } = await api.get<Paper[]>('/papers', { params })
  return data
}

export async function fetchPaper(id: number): Promise<Paper> {
  const { data } = await api.get<Paper>(`/papers/${id}`)
  return data
}

export async function deletePaper(id: number): Promise<{ message: string }> {
  const { data } = await api.delete<{ message: string }>(`/papers/${id}`)
  return data
}

export interface ImportPaperResult {
  message: string
  paper_id: number
  arxiv_id: string
  title: string
  is_new: boolean
}

export async function importPaper(arxivUrl: string): Promise<ImportPaperResult> {
  const { data } = await api.post<ImportPaperResult>('/papers/import', null, {
    params: { arxiv_url: arxivUrl },
  })
  return data
}

export async function fetchPendingPaperIds(): Promise<number[]> {
  const { data } = await api.get<{ paper_ids: number[] }>('/papers/pending')
  return data.paper_ids
}

export async function fetchStats(): Promise<Stats> {
  const { data } = await api.get<Stats>('/stats')
  return data
}

export async function triggerFetch(): Promise<{ message: string }> {
  const { data } = await api.post<{ message: string }>('/papers/fetch')
  return data
}

// Fetch stream types
export interface FetchDoneEvent {
  status: 'done'
  fetched: number
  saved: number
  message: string
}

export interface FetchStreamCallbacks {
  onStarted?: () => void
  onFetching?: (message: string) => void
  onFetched?: (count: number, message: string) => void
  onSaving?: (message: string) => void
  onDone?: (event: FetchDoneEvent) => void
  onError?: (error: Error) => void
}

/**
 * Fetch papers from arXiv with streaming progress.
 * Only fetches and saves - does NOT process papers.
 */
export function fetchPapersStream(
  callbacks: FetchStreamCallbacks,
): { abort: () => void } {
  const url = `${baseURL}/papers/fetch/stream`
  const abortController = new AbortController()

  const processStream = async () => {
    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: { Accept: 'text/event-stream' },
        signal: abortController.signal,
      })

      if (!response.ok) {
        const errorText = await response.text()
        callbacks.onError?.(new Error(errorText || `HTTP Error: ${response.status}`))
        return
      }

      const reader = response.body?.getReader()
      if (!reader) {
        callbacks.onError?.(new Error('Failed to get response reader'))
        return
      }

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const events = buffer.split('\n\n')
        buffer = events.pop() || ''

        for (const eventStr of events) {
          if (!eventStr.trim()) continue

          const lines = eventStr.trim().split('\n')
          let eventType = ''
          let dataStr = ''

          for (const line of lines) {
            if (line.startsWith('event:')) {
              eventType = line.slice(6).trim()
            } else if (line.startsWith('data:')) {
              dataStr = line.slice(5).trim()
            }
          }

          if (!dataStr) continue

          try {
            const data = JSON.parse(dataStr)
            switch (eventType) {
              case 'started':
                callbacks.onStarted?.()
                break
              case 'fetching':
                callbacks.onFetching?.(data.message)
                break
              case 'fetched':
                callbacks.onFetched?.(data.count, data.message)
                break
              case 'saving':
                callbacks.onSaving?.(data.message)
                break
              case 'done':
                callbacks.onDone?.(data as FetchDoneEvent)
                break
              case 'error':
                callbacks.onError?.(new Error(data.error))
                break
            }
          } catch {
            // Skip malformed JSON
          }
        }
      }
    } catch (error) {
      if ((error as Error).name === 'AbortError') return
      callbacks.onError?.(error as Error)
    }
  }

  processStream()

  return { abort: () => abortController.abort() }
}

export async function triggerBatchProcess(): Promise<{ message: string; count: number }> {
  const { data } = await api.post<{ message: string; count: number }>('/papers/process/batch')
  return data
}

// Batch processing stream types
export interface BatchStartedEvent {
  total: number
}

export interface BatchPaperCompletedEvent {
  paper_id: number
  title: string
  processed: number
  total: number
}

export interface BatchPaperProcessingEvent {
  paper_id: number
  title: string
}

export interface BatchPaperFailedEvent {
  paper_id: number
  title?: string
  error?: string
  failed: number
  total: number
}

export interface BatchDoneEvent {
  status: 'completed' | 'no_papers'
  processed?: number
  failed?: number
  total?: number
  message?: string
}

export interface BatchStreamCallbacks {
  onStarted?: (event: BatchStartedEvent) => void
  onPaperProcessing?: (event: BatchPaperProcessingEvent) => void
  onPaperCompleted?: (event: BatchPaperCompletedEvent) => void
  onPaperFailed?: (event: BatchPaperFailedEvent) => void
  onDone?: (event: BatchDoneEvent) => void
  onError?: (error: Error) => void
}

/**
 * Process all pending/failed papers with streaming progress updates.
 * Uses Server-Sent Events (SSE) to receive real-time updates.
 */
export function processBatchStream(
  callbacks: BatchStreamCallbacks,
): { abort: () => void } {
  const url = `${baseURL}/papers/process/batch/stream`
  const abortController = new AbortController()

  const processStream = async () => {
    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: {
          Accept: 'text/event-stream',
        },
        signal: abortController.signal,
      })

      if (!response.ok) {
        const errorText = await response.text()
        callbacks.onError?.(new Error(errorText || `HTTP Error: ${response.status}`))
        return
      }

      const reader = response.body?.getReader()
      if (!reader) {
        callbacks.onError?.(new Error('Failed to get response reader'))
        return
      }

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        const events = buffer.split('\n\n')
        buffer = events.pop() || ''

        for (const eventStr of events) {
          if (!eventStr.trim()) continue

          const lines = eventStr.trim().split('\n')
          let eventType = ''
          let dataStr = ''

          for (const line of lines) {
            if (line.startsWith('event:')) {
              eventType = line.slice(6).trim()
            } else if (line.startsWith('data:')) {
              dataStr = line.slice(5).trim()
            }
          }

          if (!dataStr) continue

          try {
            const data = JSON.parse(dataStr)
            switch (eventType) {
              case 'started':
                callbacks.onStarted?.(data as BatchStartedEvent)
                break
              case 'paper_processing':
                callbacks.onPaperProcessing?.(data as BatchPaperProcessingEvent)
                break
              case 'paper_completed':
                callbacks.onPaperCompleted?.(data as BatchPaperCompletedEvent)
                break
              case 'paper_failed':
                callbacks.onPaperFailed?.(data as BatchPaperFailedEvent)
                break
              case 'done':
                callbacks.onDone?.(data as BatchDoneEvent)
                break
            }
          } catch {
            // Skip malformed JSON
          }
        }
      }
    } catch (error) {
      if ((error as Error).name === 'AbortError') {
        return
      }
      callbacks.onError?.(error as Error)
    }
  }

  processStream()

  return {
    abort: () => abortController.abort(),
  }
}

export async function processPaper(id: number): Promise<{ message: string }> {
  const { data } = await api.post<{ message: string }>(`/papers/${id}/process`)
  return data
}

export async function fetchSettings(): Promise<AppSettings> {
  const { data } = await api.get<AppSettings>('/settings')
  return data
}

export async function updateSettings(settings: AppSettings): Promise<AppSettings> {
  const { data } = await api.put<AppSettings>('/settings', settings)
  return data
}

// Streaming API Types
export interface StreamCallbacks {
  onProgress?: (event: StreamProgressEvent) => void
  onThinking?: (thought: string, accumulated: string) => void
  onAnswer?: (answer: string, accumulated: string) => void
  onResult?: (result: DifyAnalysisResult) => void
  onError?: (error: StreamErrorEvent) => void
  onDone?: () => void
}

/**
 * Process a paper with streaming response for real-time updates.
 * Uses Server-Sent Events (SSE) to receive incremental updates.
 */
export function processPaperStream(
  id: number,
  callbacks: StreamCallbacks,
): { abort: () => void } {
  const url = `${baseURL}/papers/${id}/process/stream`
  const abortController = new AbortController()

  let accumulatedThought = ''
  let accumulatedAnswer = ''

  const processStream = async () => {
    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: {
          Accept: 'text/event-stream',
        },
        signal: abortController.signal,
      })

      if (!response.ok) {
        const errorText = await response.text()
        callbacks.onError?.({
          error: `http_${response.status}`,
          message: errorText || `HTTP Error: ${response.status}`,
        })
        return
      }

      const reader = response.body?.getReader()
      if (!reader) {
        callbacks.onError?.({
          error: 'no_reader',
          message: 'Failed to get response reader',
        })
        return
      }

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // Process complete SSE events (separated by double newlines)
        const events = buffer.split('\n\n')
        buffer = events.pop() || '' // Keep incomplete event in buffer

        for (const eventStr of events) {
          if (!eventStr.trim()) continue

          const { eventType, data } = parseSSEEvent(eventStr)
          if (!eventType || !data) continue

          handleStreamEvent(
            eventType,
            data,
            callbacks,
            { accumulatedThought, accumulatedAnswer },
            (thought) => { accumulatedThought = thought },
            (answer) => { accumulatedAnswer = answer },
          )
        }
      }
    } catch (error) {
      if ((error as Error).name === 'AbortError') {
        return // Intentional abort
      }
      callbacks.onError?.({
        error: 'stream_error',
        message: (error as Error).message || 'Stream processing failed',
      })
    }
  }

  processStream()

  return {
    abort: () => abortController.abort(),
  }
}

function parseSSEEvent(eventStr: string): {
  eventType: StreamEventType | null
  data: unknown
} {
  const lines = eventStr.trim().split('\n')
  let eventType: StreamEventType | null = null
  let dataStr = ''

  for (const line of lines) {
    if (line.startsWith('event:')) {
      eventType = line.slice(6).trim() as StreamEventType
    } else if (line.startsWith('data:')) {
      dataStr = line.slice(5).trim()
    }
  }

  if (!dataStr) return { eventType: null, data: null }

  try {
    return { eventType, data: JSON.parse(dataStr) }
  } catch {
    return { eventType: null, data: null }
  }
}

function handleStreamEvent(
  eventType: StreamEventType,
  data: unknown,
  callbacks: StreamCallbacks,
  accumulated: { accumulatedThought: string; accumulatedAnswer: string },
  setThought: (thought: string) => void,
  setAnswer: (answer: string) => void,
) {
  switch (eventType) {
    case 'progress':
      callbacks.onProgress?.(data as StreamProgressEvent)
      break

    case 'thinking': {
      const thinkingData = data as StreamThinkingEvent
      const newThought = accumulated.accumulatedThought + thinkingData.thought
      setThought(newThought)
      callbacks.onThinking?.(thinkingData.thought, newThought)
      break
    }

    case 'answer': {
      const answerData = data as StreamAnswerEvent
      const newAnswer = accumulated.accumulatedAnswer + answerData.answer
      setAnswer(newAnswer)
      callbacks.onAnswer?.(answerData.answer, newAnswer)
      break
    }

    case 'result':
      callbacks.onResult?.(data as DifyAnalysisResult)
      break

    case 'error':
      callbacks.onError?.(data as StreamErrorEvent)
      break

    case 'done':
      callbacks.onDone?.()
      break
  }
}

/**
 * Get error message for display based on error type.
 */
export function getStreamErrorMessage(error: StreamErrorEvent): string {
  switch (error.error) {
    case 'entity_too_large':
      return '论文内容过长，请尝试手动处理'
    case 'timeout':
      return '分析超时，请稍后重试'
    case 'rate_limit':
      return '请求过于频繁，请稍后重试'
    case 'dify_error':
      return `Dify服务错误: ${error.message}`
    default:
      return error.message || '未知错误'
  }
}
