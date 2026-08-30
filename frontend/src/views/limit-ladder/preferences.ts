import {
  DEFAULT_LIMIT_LADDER_FILTERS,
  LIMIT_LADDER_WINDOWS,
  normalizeLimitLadderFilters,
  type LimitLadderBoard,
  type LimitLadderFilters,
  type LimitLadderWindow,
} from '@/api/limitLadder'

export interface LimitLadderPreferenceV1 extends Record<string, unknown> {
  schemaVersion: 1
  window: LimitLadderWindow
  ignoreSt: boolean
  boards: LimitLadderBoard[]
  showAnalysisPanel: boolean
}

export const DEFAULT_LIMIT_LADDER_PREFERENCE: LimitLadderPreferenceV1 = {
  schemaVersion: 1,
  window: DEFAULT_LIMIT_LADDER_FILTERS.window,
  ignoreSt: DEFAULT_LIMIT_LADDER_FILTERS.ignoreSt,
  boards: [...DEFAULT_LIMIT_LADDER_FILTERS.boards],
  showAnalysisPanel: false,
}

const VALID_BOARDS = new Set<LimitLadderBoard>(DEFAULT_LIMIT_LADDER_FILTERS.boards)

/**
 * 兼容无 schemaVersion 的旧值；未知新版本和非法字段按字段回退系统默认，
 * 避免损坏的个人偏好阻断页面。
 */
export function normalizeLimitLadderPreference(value: unknown): LimitLadderPreferenceV1 {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return { ...DEFAULT_LIMIT_LADDER_PREFERENCE, boards: [...DEFAULT_LIMIT_LADDER_PREFERENCE.boards] }
  }
  const input = value as Partial<Record<keyof LimitLadderPreferenceV1, unknown>>
  if (input.schemaVersion !== undefined && input.schemaVersion !== 1) {
    return { ...DEFAULT_LIMIT_LADDER_PREFERENCE, boards: [...DEFAULT_LIMIT_LADDER_PREFERENCE.boards] }
  }
  const rawBoards = Array.isArray(input.boards) ? input.boards : []
  const boardsValid = rawBoards.length > 0
    && rawBoards.every((board) => VALID_BOARDS.has(board as LimitLadderBoard))
  const boards = boardsValid
    ? Array.from(new Set(rawBoards as LimitLadderBoard[]))
    : [...DEFAULT_LIMIT_LADDER_PREFERENCE.boards]
  return {
    schemaVersion: 1,
    window: LIMIT_LADDER_WINDOWS.includes(Number(input.window) as LimitLadderWindow)
      ? Number(input.window) as LimitLadderWindow
      : DEFAULT_LIMIT_LADDER_PREFERENCE.window,
    ignoreSt: typeof input.ignoreSt === 'boolean'
      ? input.ignoreSt
      : DEFAULT_LIMIT_LADDER_PREFERENCE.ignoreSt,
    boards,
    showAnalysisPanel: typeof input.showAnalysisPanel === 'boolean'
      ? input.showAnalysisPanel
      : DEFAULT_LIMIT_LADDER_PREFERENCE.showAnalysisPanel,
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
