export type RelatedBoardConfidence = 'high' | 'medium' | 'low'

export interface RelatedBoardWinner {
  board_code: string
  name: string
  score: number
  corr_20: number
  corr_60: number
  sample_20: number
  sample_60: number
  confidence: RelatedBoardConfidence
  history?: RelatedBoardHistory
}

export interface RelatedBoardBenchmark {
  code: string | null
  name: string | null
  fallback: boolean
}

export interface RelatedBoardHistory {
  as_of_date: string
  benchmark: RelatedBoardBenchmark
}

export interface RelatedBoardEmptyReason {
  code: 'no_candidates' | 'insufficient_samples' | 'invalid_correlation'
  message: string
  max_sample_20: number | null
  required_sample_20: number
  max_sample_60: number | null
  required_sample_60: number
}

export interface StockRelatedBoards {
  as_of_date: string | null
  benchmark: RelatedBoardBenchmark
  industry: RelatedBoardWinner | null
  concept: RelatedBoardWinner | null
  industry_empty_reason?: RelatedBoardEmptyReason | null
  concept_empty_reason?: RelatedBoardEmptyReason | null
  unavailable_reason?: 'as_of_mismatch' | 'first_load_pending'
}
