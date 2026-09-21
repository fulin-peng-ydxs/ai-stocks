import {
  DEFAULT_LIMIT_LADDER_FILTERS,
  LIMIT_LADDER_WINDOWS,
  normalizeLimitLadderFilters,
  type LimitLadderBoard,
  type LimitLadderFilters,
  type LimitLadderWindow,
} from '@/api/limitLadder'
import {
  DEFAULT_LIMIT_LADDER_CARD_SORT,
  DEFAULT_LIMIT_LADDER_CARD_SORT_ORDER,
  defaultLimitLadderCardSortOrder,
  normalizeLimitLadderCardSort,
  normalizeLimitLadderCardSortOrder,
  type LimitLadderCardSort,
  type LimitLadderCardSortOrder,
} from './sorting'

export interface LimitLadderPreferenceV1 extends Record<string, unknown> {
  schemaVersion: 1
  window: LimitLadderWindow
  ignoreSt: boolean
  boards: LimitLadderBoard[]
  cardSort: LimitLadderCardSort
  cardSortOrder: LimitLadderCardSortOrder
  adjustMode: '' | 'qfq' | 'hfq'
}

export const DEFAULT_LIMIT_LADDER_PREFERENCE: LimitLadderPreferenceV1 = {
  schemaVersion: 1,
  window: DEFAULT_LIMIT_LADDER_FILTERS.window,
  ignoreSt: DEFAULT_LIMIT_LADDER_FILTERS.ignoreSt,
  boards: [...DEFAULT_LIMIT_LADDER_FILTERS.boards],
  cardSort: DEFAULT_LIMIT_LADDER_CARD_SORT,
  cardSortOrder: DEFAULT_LIMIT_LADDER_CARD_SORT_ORDER,
  adjustMode: 'qfq',
}

const VALID_BOARDS = new Set<LimitLadderBoard>(DEFAULT_LIMIT_LADDER_FILTERS.boards)

function defaultPreference(): LimitLadderPreferenceV1 {
  return {
    ...DEFAULT_LIMIT_LADDER_PREFERENCE,
    boards: [...DEFAULT_LIMIT_LADDER_PREFERENCE.boards],
  }
}

/**
 * 兼容无 schemaVersion 的旧值；未知新版本和非法字段按字段回退系统默认，
 * 避免损坏的个人偏好阻断页面。
 */
export function normalizeLimitLadderPreference(value: unknown): LimitLadderPreferenceV1 {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return defaultPreference()
  }
  const input = value as Partial<Record<keyof LimitLadderPreferenceV1, unknown>>
  if (input.schemaVersion !== undefined && input.schemaVersion !== 1) {
    return defaultPreference()
  }
  const rawBoards = Array.isArray(input.boards) ? input.boards : []
  const boardsValid = rawBoards.length > 0
    && rawBoards.every((board) => VALID_BOARDS.has(board as LimitLadderBoard))
  const boards = boardsValid
    ? Array.from(new Set(rawBoards as LimitLadderBoard[]))
    : [...DEFAULT_LIMIT_LADDER_PREFERENCE.boards]
  const cardSort = normalizeLimitLadderCardSort(input.cardSort)
  return {
    schemaVersion: 1,
    window: LIMIT_LADDER_WINDOWS.includes(Number(input.window) as LimitLadderWindow)
      ? Number(input.window) as LimitLadderWindow
      : DEFAULT_LIMIT_LADDER_PREFERENCE.window,
    ignoreSt: typeof input.ignoreSt === 'boolean'
      ? input.ignoreSt
      : DEFAULT_LIMIT_LADDER_PREFERENCE.ignoreSt,
    boards,
    cardSort,
    // 旧偏好没有方向字段：文本字段延续原升序，数字字段延续原降序。
    cardSortOrder: normalizeLimitLadderCardSortOrder(
      input.cardSortOrder,
      defaultLimitLadderCardSortOrder(cardSort),
    ),
    adjustMode: input.adjustMode === '' || input.adjustMode === 'hfq' ? input.adjustMode : 'qfq',
  }
}

export function filtersFromLimitLadderPreference(
  preference: LimitLadderPreferenceV1,
): LimitLadderFilters {
  return normalizeLimitLadderFilters({
    ...DEFAULT_LIMIT_LADDER_FILTERS,
    window: preference.window,
    ignoreSt: preference.ignoreSt,
    boards: preference.boards,
  })
}
