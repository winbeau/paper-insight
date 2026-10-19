/**
 * Static web demo (GitHub Pages): an in-browser stand-in for the local backend.
 *
 * All data in ./data.json comes from a real run of the app: research directions filled
 * by the AI agent (with its arXiv keyword tests), real arXiv papers, and their real
 * MinerU + DeepSeek analyses. Streams (paper analysis, "Fill with AI") are replays of
 * the recorded server-sent events, with long waits compressed. State lives in memory,
 * so edits and deletions last until the page is reloaded.
 */
import { AxiosError, type AxiosInstance, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import { setSSEOverride } from '../services/api'
import type { AppSettings, Direction, Paper } from '../types/paper'

type Recorded = [number, string, unknown][]

interface DemoData {
  constants: { arxiv_options: Array<{ code: string; name: string; desc: string }> }
  settings: AppSettings
  papers: Paper[]
  final: Record<string, Paper>
  runs: Record<string, Recorded>
  agents: Record<string, { description: string; events: Recorded }>
  usage: unknown
  mineru: Record<string, unknown>
  storage: { pdfs: number; parsed: number; thumbnails: number; total: number }
}

export const DEMO_ONLY = '在线演示不支持此操作，请下载 macOS 应用体验完整功能'
const SPEED = 1.6          // replay faster than real time
const MAX_GAP_MS = 2200    // compress long waits (MinerU parse, model start-up)

interface ActiveRun { cancel: () => void; emit: (type: string, data: unknown) => void }

let data: DemoData
let papers: Paper[] = []
let settings: AppSettings
const active = new Map<number, ActiveRun>()

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T
const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

// --- Replay ---------------------------------------------------------------------------

function replay(
  events: Recorded,
  emit: (type: string, data: unknown) => void,
  onEnd?: () => void,
  maxGap = MAX_GAP_MS,
): () => void {
  let index = 0
  let timer: ReturnType<typeof setTimeout>
  let cancelled = false
  const next = () => {
    if (cancelled) return
    const [t, type, payload] = events[index]
    emit(type, clone(payload))
    index += 1
    if (index < events.length) {
      timer = setTimeout(next, Math.min((events[index][0] - t) / SPEED, maxGap))
    } else {
      onEnd?.()
    }
  }
  timer = setTimeout(next, 150)
  return () => {
    cancelled = true
    clearTimeout(timer)
  }
}

// --- Helpers mirroring the backend ----------------------------------------------------

function deriveFocusKeywords(focus: string): string[] {
  let raw = (focus || '').trim()
  if (!raw) return []
  if (raw.includes(';')) return raw.split(/;+/).map(k => k.trim()).filter(Boolean)
  raw = raw.replace(/\bANDNOT\s*\([^()]*\)/gi, ' ').replace(/\bANDNOT\s+\S+/gi, ' ')
  const keywords = raw.split(/\bOR\b|\bAND\b/i)
    .map(part => part.trim().replace(/^[()]+|[()]+$/g, '').trim()
      .replace(/^(?:all|abs|ti):/i, '').trim().replace(/^"|"$/g, '').trim())
    .filter(Boolean)
  return [...new Set(keywords)]
}

function visible(p: Paper) {
  return p.processing_status !== 'skipped'
}

function byDirection(directionId: unknown) {
  return directionId == null || directionId === '' ? papers : papers.filter(p => p.direction_id === Number(directionId))
}

function stats(directionId: unknown) {
  const list = byDirection(directionId).filter(visible)
  const processed = list.filter(p => p.is_processed)
  return {
    total_papers: list.length,
    processed_papers: processed.length,
    high_relevance_papers: processed.filter(p => (p.relevance_score ?? 0) >= 9).length,
    pending_processing: list.length - processed.length,
  }
}

function directionSummaries() {
  return settings.directions.map(d => {
    const list = papers.filter(p => p.direction_id === d.id && visible(p))
    return {
      id: d.id,
      name: d.name,
      focus_keywords: d.focus_keywords,
      total: list.length,
      pending: list.filter(p => !p.is_processed && p.processing_status !== 'processing').length,
      processing: list.filter(p => p.processing_status === 'processing').length,
      high: list.filter(p => (p.relevance_score ?? 0) >= 9).length,
    }
  })
}

function sortFeed(list: Paper[]) {
  return [...list].sort((a, b) =>
    Number(b.is_processed) - Number(a.is_processed)
    || (b.relevance_score ?? -1) - (a.relevance_score ?? -1)
    || b.published.localeCompare(a.published))
}

function deletePapers(ids: number[]) {
  const gone = new Set(ids.filter(id => !active.has(id)))
  papers = papers.filter(p => !gone.has(p.id))
  return { deleted: gone.size, skipped_active: ids.length - gone.size, freed_bytes: 0 }
}

function historyMatches(params: Record<string, unknown>) {
  const q = String(params.q ?? '').trim().toLowerCase()
  return byDirection(params.direction_id)
    .filter(p => !params.status || p.processing_status === params.status)
    .filter(p => !q || p.title.toLowerCase().includes(q) || p.arxiv_id.toLowerCase().includes(q))
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
}

function syncDirections(incoming: Direction[]) {
  let nextId = Math.max(0, ...settings.directions.map(d => d.id ?? 0)) + 1
  const kept = incoming.map((d, position) => ({
    ...d,
    id: d.id ?? nextId++,
    name: d.name.trim() || `研究方向 ${position + 1}`,
    focus_keywords: deriveFocusKeywords(d.research_focus),
    _key: undefined,
  }))
  const keptIds = new Set(kept.map(d => d.id))
  papers = papers.filter(p => p.direction_id == null || keptIds.has(p.direction_id))
  settings.directions = kept
}

// --- REST routes ---------------------------------------------------------------------

type Handler = (params: Record<string, unknown>, body: any, match: RegExpMatchArray) => unknown
const routes: Array<[string, RegExp, Handler]> = [
  ['get', /^\/health$/, () => ({ status: 'healthy', version: 'demo' })],
  ['get', /^\/constants$/, () => data.constants],
  ['get', /^\/settings$/, () => clone(settings)],
  ['put', /^\/settings$/, (_p, body) => {
    const { directions, ...rest } = body as AppSettings
    settings = { ...settings, ...clone(rest), providers: settings.providers }  // keys stay demo keys
    if (directions) syncDirections(directions)
    return clone(settings)
  }],
  ['get', /^\/directions$/, () => directionSummaries()],
  ['get', /^\/stats$/, params => stats(params.direction_id)],
  ['get', /^\/usage$/, () => data.usage],
  ['get', /^\/papers$/, params =>
    sortFeed(byDirection(params.direction_id).filter(visible)).slice(0, Number(params.limit ?? 100))],
  ['get', /^\/papers\/pending$/, params => ({
    paper_ids: byDirection(params.direction_id)
      .filter(p => !p.is_processed && ['pending', 'failed'].includes(p.processing_status))
      .map(p => p.id),
  })],
  ['get', /^\/papers\/(\d+)$/, (_p, _b, m) => {
    const paper = papers.find(p => p.id === Number(m[1]))
    if (!paper) throw httpError(404, 'Paper not found')
    return clone(paper)
  }],
  ['delete', /^\/papers\/(\d+)$/, (_p, _b, m) => {
    const result = deletePapers([Number(m[1])])
    if (result.skipped_active) throw httpError(409, 'Paper is being analyzed')
    return { message: 'Paper deleted successfully' }
  }],
  ['post', /^\/papers\/import$/, () => { throw httpError(400, DEMO_ONLY) }],
  ['post', /^\/papers\/process\/prepare$/, () => ({ queued: 0 })],
  ['post', /^\/papers\/process\/stop$/, () => {
    const stopped = [...active.entries()]
    for (const [paperId, run] of stopped) {
      run.cancel()
      active.delete(paperId)
      setStatus(paperId, 'pending')
      run.emit('error', { error: 'stopped', message: '已手动停止' })
    }
    return { stopped: stopped.length, parses_cancelled: 0 }
  }],
  ['get', /^\/papers\/process\/status$/, () => ({ active: [...active.keys()], parse_queued: 0, parse_running: 0 })],
  ['get', /^\/history$/, params => {
    const matches = historyMatches(params)
    const offset = Number(params.offset ?? 0)
    const limit = Number(params.limit ?? 50)
    const names = new Map(settings.directions.map(d => [d.id, d.name]))
    return {
      total: matches.length,
      items: matches.slice(offset, offset + limit).map(p => ({
        id: p.id, arxiv_id: p.arxiv_id, title: p.title, direction_id: p.direction_id,
        direction_name: names.get(p.direction_id) ?? '', processing_status: p.processing_status,
        relevance_score: p.relevance_score, created_at: p.created_at, published: p.published,
      })),
      storage: data.storage,
    }
  }],
  ['post', /^\/history\/delete$/, (_p, body) => deletePapers(body.paper_ids)],
  ['post', /^\/history\/clear$/, (_p, body) => deletePapers(historyMatches(body).map(p => p.id))],
  ['post', /^\/history\/prune$/, () => ({ removed: 0, freed_bytes: 0, storage: data.storage })],
  ['post', /^\/providers\/test$/, () => ({ ok: true, reply: 'pong（演示）', latency_ms: 860 })],
  ['post', /^\/providers\/models$/, () => ({ ok: true, models: ['deepseek-flash', 'deepseek-v4-pro'] })],
  ['get', /^\/mineru\/status$/, () => data.mineru],
  ['post', /^\/mineru\/.*$/, () => { throw httpError(400, DEMO_ONLY) }],
]

function httpError(status: number, detail: string) {
  return Object.assign(new Error(detail), { status, detail })
}

function setStatus(paperId: number, status: string) {
  const paper = papers.find(p => p.id === paperId)
  if (paper) paper.processing_status = status
}

async function adapter(config: InternalAxiosRequestConfig): Promise<AxiosResponse> {
  await sleep(90)
  const url = new URL(config.url ?? '/', 'http://demo')
  const params: Record<string, unknown> = { ...Object.fromEntries(url.searchParams), ...(config.params ?? {}) }
  const body = typeof config.data === 'string' && config.data ? JSON.parse(config.data) : config.data
  const method = (config.method ?? 'get').toLowerCase()
  const route = routes.find(([m, re]) => m === method && re.test(url.pathname))
  const respond = (status: number, payload: unknown): AxiosResponse =>
    ({ data: payload, status, statusText: String(status), headers: {}, config, request: {} })
  if (!route) {
    throw new AxiosError('Not found', 'ERR_BAD_REQUEST', config, {}, respond(404, { detail: 'Not found' }))
  }
  try {
    return respond(200, route[2](params, body, url.pathname.match(route[1])!))
  } catch (e) {
    const err = e as { status?: number; detail?: string; message: string }
    const response = respond(err.status ?? 500, { detail: err.detail ?? err.message })
    throw new AxiosError(err.detail ?? err.message, 'ERR_BAD_REQUEST', config, {}, response)
  }
}

// --- Streams ---------------------------------------------------------------------------

function streamPaper(paperId: number, emit: (type: string, data: unknown) => void, fail: (e: Error, s?: number) => void) {
  const paper = papers.find(p => p.id === paperId)
  if (!paper) {
    fail(new Error('Paper not found'), 404)
    return () => {}
  }
  if (active.has(paperId)) {
    emit('error', { error: 'busy', message: '该论文正在分析中' })
    return () => {}
  }
  const events = data.runs[String(paperId)]
  if (!events) {
    emit('error', { error: 'config_error', message: DEMO_ONLY })
    return () => {}
  }
  paper.processing_status = 'processing'
  const cancel = replay(events, (type, payload) => {
    if (type === 'result') {
      const final = data.final[String(paperId)]
      const index = papers.findIndex(p => p.id === paperId)
      if (final && index !== -1) papers[index] = { ...clone(final), processing_status: 'processing' }
    } else if (type === 'done') {
      const final = data.final[String(paperId)]
      setStatus(paperId, final?.processing_status ?? 'processed')
      active.delete(paperId)
    }
    emit(type, payload)
  })
  active.set(paperId, { cancel, emit })
  return () => {
    // Client went away mid-run (cf. the backend marking it interrupted)
    if (active.has(paperId)) {
      cancel()
      active.delete(paperId)
      setStatus(paperId, 'pending')
    }
  }
}

function streamAgent(body: { description?: string }, emit: (type: string, data: unknown) => void) {
  const description = body?.description ?? ''
  const names = Object.keys(data.agents)
  const robot = /机器人|抓取|机械臂|robot|grasp|manipulat/i.test(description)
  const name = names.find(n => (robot ? /机器人|抓取/.test(n) : !/机器人|抓取/.test(n))) ?? names[0]
  const events: Recorded = [
    [0, 'status', { message: '演示：回放一次真实的智能填写过程（DeepSeek + arXiv 实测）' }],
    ...data.agents[name].events.map(([t, type, payload]) => [t + 600, type, payload] as [number, string, unknown]),
  ]
  return replay(events, emit, undefined, 1400)
}

function sseReader(
  path: string,
  onEvent: (type: string, data: unknown) => void,
  onFailure: (error: Error, status?: number) => void,
  body?: unknown,
) {
  let cancel = () => {}
  const paperMatch = path.match(/^\/papers\/(\d+)\/process\/stream/)
  if (paperMatch) {
    cancel = streamPaper(Number(paperMatch[1]), onEvent, onFailure)
  } else if (path.startsWith('/papers/fetch/stream')) {
    cancel = replay([
      [0, 'started', { status: 'started' }],
      [300, 'fetching', { status: 'fetching', message: '正在从 arXiv 获取论文...' }],
      [2200, 'fetched', { status: 'fetched', message: '获取到 0 篇论文', count: 0 }],
      [2400, 'done', { status: 'done', fetched: 0, saved: 0, message: '演示数据：没有新论文' }],
    ], onEvent)
  } else if (path.startsWith('/research/autofill')) {
    cancel = streamAgent(body as { description?: string }, onEvent)
  } else if (path.startsWith('/mineru/install/stream')) {
    cancel = replay([[0, 'done', { error: DEMO_ONLY, step: '', status: data.mineru }]], onEvent)
  } else {
    onFailure(new Error('Not available in the demo'), 404)
  }
  return { abort: () => cancel() }
}

export async function installDemo(api: AxiosInstance) {
  data = (await import('./data.json')).default as unknown as DemoData
  papers = clone(data.papers)
  settings = clone(data.settings)
  api.defaults.adapter = adapter
  setSSEOverride(sseReader)
}
