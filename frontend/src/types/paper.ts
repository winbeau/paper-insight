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
export interface ConceptBridging {
  source_concept: string
  target_concept: string
  mechanism_transfer: string
}

export interface DifyAnalysisResult {
  paper_essence: string
  concept_bridging: ConceptBridging
  visual_verification: string
  relevance_score: number
  relevance_reason: string
  heuristic_suggestion: string
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

export interface ProgressStep {
  label: string
  status: 'pending' | 'active' | 'done' | 'error'
  group?: number // Steps with same group number are displayed in parallel
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
