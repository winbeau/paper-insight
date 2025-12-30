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

export type FilterType = 'all' | 'high' | 'medium' | 'low'
export type StatusFilter = 'all' | 'processed' | 'pending'
