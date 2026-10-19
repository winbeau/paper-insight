import axios from 'axios'
import type {
  Paper,
  Stats,
  AppSettings,
  AnalysisResult,
  ArxivOption,
  MineruStatus,
  Provider,
  ProviderModelsResult,
  ProviderTestResult,
  StreamProgressEvent,
  StreamStartedEvent,
  StreamThinkingEvent,
  StreamAnswerEvent,
  StreamErrorEvent,
} from '../types/paper'
import { apiBase } from '../utils/urls'
import { getLogger } from '../utils/logger'

const logger = getLogger('api')

export const api = axios.create({
  baseURL: apiBase,
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

export async function fetchConstants(): Promise<{ arxiv_options: ArxivOption[] }> {
  const { data } = await api.get<{ arxiv_options: ArxivOption[] }>('/constants')
  return data
}

export async function fetchSettings(): Promise<AppSettings> {
  const { data } = await api.get<AppSettings>('/settings')
  return data
}

export async function updateSettings(settings: Partial<AppSettings>): Promise<AppSettings> {
  const { data } = await api.put<AppSettings>('/settings', settings)
  return data
}

// --- Model providers ---

export async function testProvider(
  provider: Provider,
  model: string,
  kind: 'chat' | 'vision' = 'chat',
): Promise<ProviderTestResult> {
  const { data } = await api.post<ProviderTestResult>(
    '/providers/test',
    { provider, model, kind },
    { timeout: 120000 },
  )
  return data
}

export async function listProviderModels(provider: Provider): Promise<ProviderModelsResult> {
  const { data } = await api.post<ProviderModelsResult>(
    '/providers/models',
    { provider },
    { timeout: 60000 },
  )
  return data
}

// --- Local MinerU runtime ---

export async function fetchMineruStatus(): Promise<MineruStatus> {
  const { data } = await api.get<MineruStatus>('/mineru/status')
  return data
}

export async function startMineruInstall(tier: string, source: string): Promise<MineruStatus> {
  const { data } = await api.post<MineruStatus>('/mineru/install', { tier, source })
  return data
}

export async function cancelMineruInstall(): Promise<MineruStatus> {
  const { data } = await api.post<MineruStatus>('/mineru/install/cancel', null, { timeout: 60000 })
  return data
}

export async function uninstallMineru(): Promise<MineruStatus> {
  const { data } = await api.post<MineruStatus>('/mineru/uninstall', null, { timeout: 120000 })
  return data
}

export async function stopMineruServer(): Promise<MineruStatus> {
  const { data } = await api.post<MineruStatus>('/mineru/server/stop', null, { timeout: 60000 })
  return data
}

// --- Server-Sent Events ---

/**
 * Read an SSE endpoint with fetch (works in WKWebView, supports abort).
 * Calls `onEvent(type, data)` for every event with a JSON `data:` line;
 * comment/padding blocks are skipped.
 */
function readSSE(
  path: string,
  onEvent: (type: string, data: unknown) => void,
  onFailure: (error: Error, status?: number) => void,
): { abort: () => void } {
  const abortController = new AbortController()

  const run = async () => {
    try {
      const response = await fetch(`${apiBase}${path}`, {
        method: 'GET',
        headers: { Accept: 'text/event-stream' },
        signal: abortController.signal,
      })
      if (!response.ok) {
        const errorText = await response.text()
        onFailure(new Error(errorText || `HTTP Error: ${response.status}`), response.status)
        return
      }
      const reader = response.body?.getReader()
      if (!reader) {
        onFailure(new Error('Failed to get response reader'))
        return
      }

      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const blocks = buffer.split('\n\n')
        buffer = blocks.pop() || ''

        for (const block of blocks) {
          let eventType = 'message'
          let dataStr = ''
          for (const line of block.split('\n')) {
            if (line.startsWith('event:')) eventType = line.slice(6).trim()
            else if (line.startsWith('data:')) dataStr += line.slice(5).trim()
          }
          if (!dataStr) continue
          let data: unknown
          try {
            data = JSON.parse(dataStr)
          } catch {
            continue // Skip malformed JSON
          }
          onEvent(eventType, data)
        }
      }
    } catch (error) {
      if ((error as Error).name === 'AbortError') return
      onFailure(error as Error)
    }
  }

  run()
  return { abort: () => abortController.abort() }
}

// Fetch stream
export interface FetchDoneEvent {
  status: 'done'
  fetched: number
  saved: number
  message: string
}

export interface FetchStreamCallbacks {
  onFetching?: (message: string) => void
  onFetched?: (count: number, message: string) => void
  onDone?: (event: FetchDoneEvent) => void
  onError?: (error: Error) => void
}

/** Fetch new papers from arXiv with streaming progress (does not analyze them). */
export function fetchPapersStream(callbacks: FetchStreamCallbacks): { abort: () => void } {
  return readSSE(
    '/papers/fetch/stream',
    (type, data) => {
      const event = data as Record<string, unknown>
      if (type === 'fetching') callbacks.onFetching?.(event.message as string)
      else if (type === 'fetched') callbacks.onFetched?.(event.count as number, event.message as string)
      else if (type === 'done') callbacks.onDone?.(event as unknown as FetchDoneEvent)
      else if (type === 'error') callbacks.onError?.(new Error(event.error as string))
    },
    (error) => callbacks.onError?.(error),
  )
}

// Analysis stream
export interface StreamCallbacks {
  onStarted?: (event: StreamStartedEvent) => void
  onProgress?: (event: StreamProgressEvent) => void
  onThinking?: (thought: string, accumulated: string) => void
  onAnswer?: (answer: string, accumulated: string) => void
  onResult?: (result: AnalysisResult) => void
  onError?: (error: StreamErrorEvent) => void
  onDone?: () => void
}

/** Run the analysis pipeline for a paper, streaming step progress and model reasoning. */
export function processPaperStream(id: number, callbacks: StreamCallbacks): { abort: () => void } {
  let accumulatedThought = ''
  let accumulatedAnswer = ''

  return readSSE(
    `/papers/${id}/process/stream`,
    (type, data) => {
      switch (type) {
        case 'started':
          callbacks.onStarted?.(data as StreamStartedEvent)
          break
        case 'progress':
          callbacks.onProgress?.(data as StreamProgressEvent)
          break
        case 'thinking': {
          const chunk = (data as StreamThinkingEvent).thought
          accumulatedThought += chunk
          callbacks.onThinking?.(chunk, accumulatedThought)
          break
        }
        case 'answer': {
          const chunk = (data as StreamAnswerEvent).answer
          accumulatedAnswer += chunk
          callbacks.onAnswer?.(chunk, accumulatedAnswer)
          break
        }
        case 'result':
          callbacks.onResult?.(data as AnalysisResult)
          break
        case 'error':
          callbacks.onError?.(data as StreamErrorEvent)
          break
        case 'done':
          callbacks.onDone?.()
          break
      }
    },
    (error, status) => callbacks.onError?.({
      error: status ? `http_${status}` : 'stream_error',
      message: error.message || 'Stream processing failed',
    }),
  )
}

// MinerU install log stream
export interface MineruInstallCallbacks {
  onLog?: (line: string) => void
  onDone?: (event: { error: string | null; step: string; status: MineruStatus }) => void
  onError?: (error: Error) => void
}

export function followMineruInstall(callbacks: MineruInstallCallbacks): { abort: () => void } {
  return readSSE(
    '/mineru/install/stream',
    (type, data) => {
      if (type === 'log') callbacks.onLog?.((data as { line: string }).line)
      else if (type === 'done') callbacks.onDone?.(data as { error: string | null; step: string; status: MineruStatus })
    },
    (error) => callbacks.onError?.(error),
  )
}

/** Human-readable message for a pipeline error event. */
export function getStreamErrorMessage(error: StreamErrorEvent): string {
  switch (error.error) {
    case 'config_error':
      return error.message || '请先在设置中配置模型'
    case 'parse_error':
      return `PDF 解析失败 (MinerU): ${error.message}`
    case 'download_error':
      return `PDF 下载失败: ${error.message}`
    case 'llm_error':
      return `模型调用失败: ${error.message}`
    case 'entity_too_large':
      return `论文内容过长: ${error.message}`
    case 'timeout':
      return '分析超时，请稍后重试'
    case 'rate_limit':
      return '请求过于频繁或额度不足，请稍后重试'
    case 'busy':
      return '该论文正在后台分析中'
    case 'interrupted':
      return '分析被中断，请重试'
    default:
      return error.message || '未知错误'
  }
}

/** Parse a stored `processing_error` ("code: message") into an error event. */
export function parseStoredError(value: string | null | undefined): StreamErrorEvent | null {
  if (!value) return null
  const index = value.indexOf(': ')
  if (index <= 0) return { error: 'unknown', message: value }
  return { error: value.slice(0, index), message: value.slice(index + 2) }
}
