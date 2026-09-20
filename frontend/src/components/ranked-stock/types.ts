import type { AdaptiveColumnRole } from '@/components/table/adaptiveColumnWidth'

export type RankedStockColumnKey =
  | 'rank' | 'code' | 'name' | 'board'
  | 'relatedIndustry' | 'relatedConcept' | 'score' | 'grade' | 'subScores'

export interface RankedStockColumn {
  key: RankedStockColumnKey
  label: string
  role: AdaptiveColumnRole
  sortable?: boolean
}

const ROLE_BY_KEY: Record<RankedStockColumnKey, AdaptiveColumnRole> = {
  rank: 'rank',
  code: 'code',
  name: 'entity',
  board: 'text',
  relatedIndustry: 'text',
  relatedConcept: 'text',
  score: 'number',
  grade: 'status',
  subScores: 'text',
}

export const rankedStockColumns = (
  keys: RankedStockColumnKey[],
): RankedStockColumn[] => keys.map((key) => ({
  key,
  label: {
    rank: '全市场排名', code: '代码', name: '名称', board: '板块',
    relatedIndustry: '行业走势', relatedConcept: '概念走势', score: '综合分',
    grade: '评级', subScores: '分项达标分',
  }[key],
  role: ROLE_BY_KEY[key],
  sortable: ['rank', 'code', 'name', 'score'].includes(key),
}))
