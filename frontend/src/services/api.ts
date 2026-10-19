import axios from 'axios'
import type {
  Paper,
  Stats,
  AppSettings,
  AnalysisResult,
  AutofillFields,
  AutofillResult,
  AutofillRound,
  DeleteResult,
  DirectionSummary,
  HistoryFilter,
  HistoryPage,
  StorageUsage,
  UsageTotals,
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
  direction_id?: number
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

export async function importPaper(arxivUrl: string, directionId?: number | null): Promise<ImportPaperResult> {
  const { data } = await api.post<ImportPaperResult>('/papers/import', null, {
    params: { arxiv_url: arxivUrl, direction_id: directionId ?? undefined },
  })
  return data
}

export async function fetchPendingPaperIds(directionId?: number | null): Promise<number[]> {
  const { data } = await api.get<{ paper_ids: number[] }>('/papers/pending', {
    params: { direction_id: directionId ?? undefined },
  })
  return data.paper_ids
}

export async function fetchStats(directionId?: number | null): Promise<Stats> {
  const { data } = await api.get<Stats>('/stats', { params: { direction_id: directionId ?? undefined } })
  return data
}

export async function fetchDirections(): Promise<DirectionSummary[]> {
  const { data } = await api.get<DirectionSummary[]>('/directions')
  return data
}

export async function fetchUsage(): Promise<{ total: UsageTotals; by_purpose: Record<string, UsageTotals> }> {
  const { data } = await api.get('/usage')
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

// --- History management ---

function filterParams(filter: HistoryFilter) {
  return {
    direction_id: filter.direction_id ?? undefined,
    status: filter.status || undefined,
    q: filter.q?.trim() || undefined,
  }
}

export async function fetchHistory(filter: HistoryFilter, offset = 0, limit = 50): Promise<HistoryPage> {
  const { data } = await api.get<HistoryPage>('/history', { params: { ...filterParams(filter), offset, limit } })
  return data
}

export async function deleteHistory(paperIds: number[], deleteFiles: boolean): Promise<DeleteResult> {
  const { data } = await api.post<DeleteResult>('/history/delete', { paper_ids: paperIds, delete_files: deleteFiles })
  return data
}

/** Delete every entry matching the filter (all entries when the filter is empty). */
export async function clearHistory(filter: HistoryFilter, deleteFiles: boolean): Promise<DeleteResult> {
  const { data } = await api.post<DeleteResult>(
    '/history/clear',
    { ...filterParams(filter), delete_files: deleteFiles },
    { timeout: 120000 },
  )
  return data
}

export async function pruneCache(): Promise<{ removed: number; freed_bytes: number; storage: StorageUsage }> {
  const { data } = await api.post('/history/prune', null, { timeout: 120000 })
  return data
}

// --- Batch processing ---

/** Queue MinerU parsing for a whole batch so it runs ahead of the analyses. */
export async function prepareBatch(paperIds: number[]): Promise<{ queued: number }> {
  const { data } = await api.post<{ queued: number }>('/papers/process/prepare', { paper_ids: paperIds })
  return data
}

/** Stop every running analysis, queued parse and the local MinerU server. */
export async function stopAllProcessing(): Promise<{ stopped: number; parses_cancelled: number }> {
  const { data } = await api.post<{ stopped: number; parses_cancelled: number }>(
    '/papers/process/stop', null, { timeout: 60000 },
  )
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

export type SSEReader = (
  path: string,
  onEvent: (type: string, data: unknown) => void,
  onFailure: (error: Error, status?: number) => void,
  body?: unknown,
) => { abort: () => void }

// The static web demo replaces the network with recorded streams (see src/demo)
let sseOverride: SSEReader | null = null
export function setSSEOverride(reader: SSEReader) {
  sseOverride = reader
}

/**
 * Read an SSE endpoint with fetch (works in WKWebView, supports abort).
 * Calls `onEvent(type, data)` for every event with a JSON `data:` line;
 * comment/padding blocks are skipped.
 */
function readSSE(
  path: string,
  onEvent: (type: string, data: unknown) => void,
  onFailure: (error: Error, status?: number) => void,
  body?: unknown,
): { abort: () => void } {
  if (sseOverride) return sseOverride(path, onEvent, onFailure, body)
  const abortController = new AbortController()

  const run = async () => {
    try {
      const response = await fetch(`${apiBase}${path}`, body === undefined
        ? { method: 'GET', headers: { Accept: 'text/event-stream' }, signal: abortController.signal }
        : {
            method: 'POST',
            headers: { Accept: 'text/event-stream', 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
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
export function fetchPapersStream(
  callbacks: FetchStreamCallbacks,
  directionId?: number | null,
): { abort: () => void } {
  return readSSE(
    directionId != null ? `/papers/fetch/stream?direction_id=${directionId}` : '/papers/fetch/stream',
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

// Research-direction auto-fill agent
export interface AutofillCallbacks {
  onStatus?: (message: string) => void
  onThinking?: (chunk: string) => void
  onDraft?: (fields: AutofillFields) => void
  onRound?: (round: AutofillRound) => void
  onResult?: (result: AutofillResult) => void
  onError?: (error: StreamErrorEvent) => void
  onDone?: () => void
}

/** Let the reasoning model fill a research direction from a plain-language description;
 *  its arXiv query is tested against arXiv over several rounds. */
export function streamResearchAutofill(
  body: { description: string; provider?: Provider; model?: string },
  callbacks: AutofillCallbacks,
): { abort: () => void } {
  return readSSE(
    '/research/autofill',
    (type, data) => {
      switch (type) {
        case 'status': callbacks.onStatus?.((data as { message: string }).message); break
        case 'thinking': callbacks.onThinking?.((data as { thought: string }).thought); break
        case 'draft': callbacks.onDraft?.(data as AutofillFields); break
        case 'round': callbacks.onRound?.(data as AutofillRound); break
        case 'result': callbacks.onResult?.(data as AutofillResult); break
        case 'error': callbacks.onError?.(data as StreamErrorEvent); break
        case 'done': callbacks.onDone?.(); break
      }
    },
    (error, status) => callbacks.onError?.({
      error: status ? `http_${status}` : 'stream_error',
      message: error.message || '请求失败',
    }),
    body,
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
    case 'stopped':
      return '已停止'
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
