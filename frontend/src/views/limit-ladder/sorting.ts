import type { LimitLadderLayer, LimitLadderStock } from '@/api/limitLadder'

export type LimitLadderCardSort = 'board' | 'industry' | 'concept' | 'return' | 'limitUps'
export type LimitLadderCardSortOrder = 'asc' | 'desc'

export const DEFAULT_LIMIT_LADDER_CARD_SORT: LimitLadderCardSort = 'limitUps'
export const DEFAULT_LIMIT_LADDER_CARD_SORT_ORDER: LimitLadderCardSortOrder = 'desc'

export const LIMIT_LADDER_CARD_SORT_OPTIONS: Array<{
  value: LimitLadderCardSort
  label: string
}> = [
  { value: 'board', label: '所属板块' },
  { value: 'industry', label: '所属行业' },
  { value: 'concept', label: '所属概念' },
  { value: 'return', label: '累计涨幅' },
  { value: 'limitUps', label: '累计涨停' },
]

const CARD_SORTS = new Set<LimitLadderCardSort>(
  LIMIT_LADDER_CARD_SORT_OPTIONS.map((option) => option.value),
)

export function normalizeLimitLadderCardSort(value: unknown): LimitLadderCardSort {
  return CARD_SORTS.has(value as LimitLadderCardSort)
    ? value as LimitLadderCardSort
    : DEFAULT_LIMIT_LADDER_CARD_SORT
}

export function defaultLimitLadderCardSortOrder(
  sort: LimitLadderCardSort,
): LimitLadderCardSortOrder {
  return sort === 'board' || sort === 'industry' || sort === 'concept' ? 'asc' : 'desc'
}

export function normalizeLimitLadderCardSortOrder(
  value: unknown,
  fallback: LimitLadderCardSortOrder = DEFAULT_LIMIT_LADDER_CARD_SORT_ORDER,
): LimitLadderCardSortOrder {
  return value === 'asc' || value === 'desc'
    ? value
    : fallback
}

function textCompare(left: string | null | undefined, right: string | null | undefined): number {
  const leftText = String(left ?? '').trim()
  const rightText = String(right ?? '').trim()
  if (!leftText || !rightText) {
    if (!leftText && !rightText) return 0
    return leftText ? -1 : 1
  }
  return leftText.localeCompare(rightText, 'zh', {
    numeric: true,
    sensitivity: 'base',
  })
}

function numberCompare(left: number | null | undefined, right: number | null | undefined): number {
  const leftValue = typeof left === 'number' && Number.isFinite(left)
    ? left
    : Number.POSITIVE_INFINITY
  const rightValue = typeof right === 'number' && Number.isFinite(right)
    ? right
    : Number.POSITIVE_INFINITY
  return leftValue - rightValue
}

function compareStock(left: LimitLadderStock, right: LimitLadderStock, sort: LimitLadderCardSort): number {
  if (sort === 'board') return textCompare(left.board, right.board)
  if (sort === 'industry') {
    return textCompare(
      left.latest_related_industry?.board_name || left.industry_name,
      right.latest_related_industry?.board_name || right.industry_name,
    )
  }
  if (sort === 'concept') {
    return textCompare(
      left.latest_related_concept?.board_name,
      right.latest_related_concept?.board_name,
    )
  }
  if (sort === 'return') return numberCompare(left.window_return_pct, right.window_return_pct)
  return numberCompare(left.window_limit_up_days, right.window_limit_up_days)
}

function hasSortValue(stock: LimitLadderStock, sort: LimitLadderCardSort): boolean {
  if (sort === 'board') return Boolean(String(stock.board ?? '').trim())
  if (sort === 'industry') {
    return Boolean(String(
      stock.latest_related_industry?.board_name || stock.industry_name || '',
    ).trim())
  }
  if (sort === 'concept') {
    return Boolean(String(stock.latest_related_concept?.board_name ?? '').trim())
  }
  const value = sort === 'return' ? stock.window_return_pct : stock.window_limit_up_days
  return typeof value === 'number' && Number.isFinite(value)
}

/**
 * 接口的连板高度是一级排序与分层边界；用户选择只在每个层级内部做二级排序。
 * ECMAScript 稳定排序会在二级字段相同时保留接口原顺序，不破坏后端确定性兜底顺序。
 */
export function sortLimitLadderLayers(
  layers: readonly LimitLadderLayer[],
  sort: LimitLadderCardSort,
  order?: LimitLadderCardSortOrder,
): LimitLadderLayer[] {
  const direction = (order ?? defaultLimitLadderCardSortOrder(sort)) === 'desc' ? -1 : 1
  return layers.map((layer) => ({
    ...layer,
    stocks: [...layer.stocks].sort((left, right) => {
      const leftHasValue = hasSortValue(left, sort)
      const rightHasValue = hasSortValue(right, sort)
      if (leftHasValue !== rightHasValue) return leftHasValue ? -1 : 1
      return compareStock(left, right, sort) * direction
    }),
  }))
}
