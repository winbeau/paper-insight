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
  summary_zh: string | null
  relevance_score: number | null
  relevance_reason: string | null
  heuristic_idea: string | null
  is_processed: boolean
  processing_status: string
  created_at: string
  processed_at: string | null
}

export interface Stats {
  total_papers: number
  processed_papers: number
  high_relevance_papers: number
  pending_processing: number
}

export interface AppSettings {
  id: number
  research_focus: string
  focus_keywords: string[]
  system_prompt: string
  arxiv_categories: string[]
}

export type FilterType = 'all' | 'high' | 'low'
export type StatusFilter = 'all' | 'processed' | 'pending'

// Dify Streaming Types
export interface TechnicalMapping {
  token_vs_patch: string
  temporal_logic: string
  frequency_domain: string
}

export interface DifyAnalysisResult {
  summary_zh: string
  relevance_score: number
  relevance_reason: string
  technical_mapping: TechnicalMapping
  heuristic_idea: string
  thought_process: string | null
}

export interface StreamProgressEvent {
  status: string
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

export interface StreamDoneEvent {
  status: string
}

export type StreamEventType = 'progress' | 'thinking' | 'answer' | 'result' | 'error' | 'done'

export interface StreamState {
  isStreaming: boolean
  progress: string
  thought: string
  answer: string
  result: DifyAnalysisResult | null
  error: StreamErrorEvent | null
}
