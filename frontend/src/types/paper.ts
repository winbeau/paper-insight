export interface Paper {
  id: number
  arxiv_id: string
  title: string
  authors: string
  abstract: string
  categories: string
  published: string
  updated: string
  pdf_url: string
  thumbnail_url: string | null
  paper_essence: string | null
  concept_bridging: string | null
  visual_verification: string | null
  relevance_score: number | null
  relevance_reason: string | null
  heuristic_suggestion: string | null
  is_processed: boolean
  processing_status: string
  processing_error: string | null  // "code: message" of the last failed run
  created_at: string
  processed_at: string | null
}

export interface Stats {
  total_papers: number
  processed_papers: number
  high_relevance_papers: number
  pending_processing: number
}

export interface ArxivOption {
  code: string
  name: string
  desc: string
}

// --- Model configuration ---

/** An OpenAI-compatible endpoint. api_key comes back masked ("••••abcd") from the API. */
export interface Provider {
  id: string
  name: string
  base_url: string
  api_key: string
  json_mode: boolean
}

export interface MineruCloudConfig {
  token: string
  model_version: 'vlm' | 'pipeline'
  is_ocr: boolean
  enable_formula: boolean
  enable_table: boolean
  language: string
}

export interface MineruLocalConfig {
  mode: 'managed' | 'external'
  tier: 'basic' | 'standard'
  source: 'huggingface' | 'modelscope'
  external_url: string
  external_api_key: string
}

export interface ModelRef {
  provider_id: string
  model: string
}

export interface VisionConfig extends ModelRef {
  enabled: boolean
  max_figures: number
  concurrency: number
  max_tokens: number
}

export interface ReasoningConfig extends ModelRef {
  temperature: number
  max_tokens: number
  max_input_chars: number
}

export interface PipelineConfig {
  parser: {
    engine: 'mineru_cloud' | 'mineru_local'
    cloud: MineruCloudConfig
    local: MineruLocalConfig
  }
  vision: VisionConfig
  reasoning: ReasoningConfig
}

export interface AppSettings {
  research_focus: string      // arXiv search query
  research_idea: string       // research context for the analysis
  focus_keywords: string[]
  system_prompt: string       // analysis prompt override (empty = built-in)
  arxiv_categories: string[]
  providers: Provider[]
  pipeline: PipelineConfig
  proxy_url: string
  last_fetch_at: string | null
}

export interface ProviderTestResult {
  ok: boolean
  reply?: string
  latency_ms?: number
  error?: string
  code?: string
}

export interface ProviderModelsResult {
  ok: boolean
  models: string[]
  error?: string
}

export interface MineruStatus {
  installed: boolean
  tier: string | null
  source: string | null
  version: string | null
  installed_at: string | null
  uv_available: boolean
  server_running: boolean
  server_url: string | null
  busy: boolean
  install: {
    running: boolean
    step: string
    error: string | null
    log_tail: string[]
  }
  disk_free_gb: number
}

export type FilterType = 'all' | 'high' | 'low'
export type StatusFilter = 'all' | 'processed' | 'pending'

// --- Analysis stream ---

export interface ConceptBridging {
  source_concept: string
  target_concept: string
  mechanism_transfer: string
}

export interface AnalysisResult {
  paper_essence: string
  concept_bridging: ConceptBridging
  visual_verification: string
  relevance_score: number
  relevance_reason: string
  heuristic_suggestion: string
  thought_process: string | null
}

export interface StreamStartedEvent {
  steps: Array<{ key: string; label: string }>
}

export interface StreamProgressEvent {
  status: 'step_started' | 'step_progress' | 'step_finished' | 'step_skipped'
  step: string
  message: string
}

export interface StreamThinkingEvent {
  thought: string
}

export interface StreamAnswerEvent {
  answer: string
}

export interface StreamErrorEvent {
  error: string
  message: string
}

export interface ProgressStep {
  key: string
  label: string
  status: 'pending' | 'active' | 'done' | 'skipped' | 'error'
  message?: string
}
