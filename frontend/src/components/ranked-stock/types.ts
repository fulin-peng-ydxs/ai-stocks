export type RankedStockColumnKey =
  | 'rank' | 'code' | 'name' | 'st' | 'board'
  | 'relatedIndustry' | 'relatedConcept' | 'score' | 'grade' | 'subScores'

export interface RankedStockColumn {
  key: RankedStockColumnKey
  label: string
  sortable?: boolean
}

export const rankedStockColumns = (
  keys: RankedStockColumnKey[],
): RankedStockColumn[] => keys.map((key) => ({
  key,
  label: {
    rank: '全市场排名', code: '代码', name: '名称', st: 'ST', board: '板块',
    relatedIndustry: '行业走势', relatedConcept: '概念走势', score: '综合分',
    grade: '评级', subScores: '分项达标分',
  }[key],
  sortable: ['rank', 'code', 'name', 'score'].includes(key),
}))
