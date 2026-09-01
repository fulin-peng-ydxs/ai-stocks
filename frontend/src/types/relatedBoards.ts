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
}

export interface RelatedBoardBenchmark {
  code: string | null
  name: string | null
  fallback: boolean
}

export interface StockRelatedBoards {
  as_of_date: string | null
  benchmark: RelatedBoardBenchmark
  industry: RelatedBoardWinner | null
  concept: RelatedBoardWinner | null
  unavailable_reason?: 'as_of_mismatch' | 'first_load_pending'
}
