export interface AppRowActionWidth {
  /** 按钮 DOM 实测宽度；缺省时按文本长度估算 */
  measured?: number
  /** 是否成功拿到实测宽度 */
  measuredOk?: boolean
}

export type AppRowActionMeasure = AppRowAction & AppRowActionWidth

/** 无实测宽度时「更多」按钮的估算宽度 */
export const MORE_BUTTON_ESTIMATED_WIDTH = 64

/** 行内按钮间的水平间距（与 AppRowActions 样式保持一致） */
export const ROW_ACTION_GAP = 8

/**
 * 计算行操作组不丢失直接入口时所需的最低内容宽度。
 *
 * 单动作至少完整显示该动作；多动作至少保留两个操作入口，可以是两个直接动作，
 * 也可以是首个直接动作和「更多」（「更多」本身计作一个入口）。只有调用方明确
 * 禁止行内动作，或全部动作都指定进入更多菜单时，才允许最低形态仅保留「更多」。
 */
export function computeRowMinimumContentWidth(
  actions: AppRowActionMeasure[],
  limit: number,
  moreButtonWidth: number = MORE_BUTTON_ESTIMATED_WIDTH,
): number {
  if (!actions.length) return 0

  const fillable = actions.filter((action) => action.placement !== 'more')
  const normalizedLimit = Math.max(0, limit)
  if (!fillable.length || normalizedLimit === 0) return moreButtonWidth

  // 枚举所有至少保留一个直接动作的有效形态，取其中最窄者：两个直接动作
  // 可能比「长动作 + 更多」更窄，因此不能把后者写死为唯一最低组合。
  let minimum = Number.POSITIVE_INFINITY
  const maxInline = Math.min(fillable.length, normalizedLimit)
  for (let inlineCount = 1; inlineCount <= maxInline; inlineCount++) {
    let width = 0
    for (let index = 0; index < inlineCount; index++) {
      width += (index > 0 ? ROW_ACTION_GAP : 0) + measureActionWidth(fillable[index])
    }
    const needsMore = inlineCount < fillable.length || actions.some((action) => (
      action.placement === 'more'
    ))
    if (needsMore) width += ROW_ACTION_GAP + moreButtonWidth
    minimum = Math.min(minimum, width)
  }
  return minimum
}

/**
 * 按可用宽度计算行内应保留几个按钮、是否出现「更多」。
 *
 * 优先级：显式 `placement: 'more'` 的动作恒入更多；其余按原始顺序贪心塞入行内，
 * 宽度装得下就留，装不下则连同剩余动作一并进更多。`limit`（来自 inlineLimit）
 * 作为行内数量的硬性上限，与宽度约束取交集。
 *
 * 兜底：`availableWidth <= 0` 或没有任何按钮实测到宽度时，退化为纯数量逻辑
 * （等价于旧行为，保证 jsdom 测试与无法测量的场景不回归）。
 */
export function computeRowLayout(
  actions: AppRowActionMeasure[],
  availableWidth: number,
  limit: number,
  moreButtonWidth: number = MORE_BUTTON_ESTIMATED_WIDTH,
): { inlineCount: number; hasMore: boolean } {
  const forced = actions.filter((a) => a.placement === 'more')
  const fillable = actions.filter((a) => a.placement !== 'more')
  const fillableCount = fillable.length

  if (availableWidth <= 0 || !fillable.some((a) => a.measuredOk)) {
    const inlineCount = Math.max(0, Math.min(fillableCount, limit))
    return { inlineCount, hasMore: inlineCount < fillableCount || forced.length > 0 }
  }

  // 遍历所有 c 取最大可行值：宽度预算在 c 从「留一个在更多」到「全部行内」时
  // 非单调（更多按钮自身也占行内宽度），因此不能用遇超宽即 break 的贪心。
  let best = 0
  for (let c = 0; c <= fillableCount; c++) {
    let width = 0
    for (let i = 0; i < c; i++) {
      width += (i > 0 ? ROW_ACTION_GAP : 0) + measureActionWidth(fillable[i])
    }
    const needMore = c < fillableCount || forced.length > 0
    const total = width + (needMore ? moreButtonWidth + (c > 0 ? ROW_ACTION_GAP : 0) : 0)
    if (total <= availableWidth) best = c
  }

  const inlineCount = Math.max(0, Math.min(best, limit))
  const hasMore = inlineCount < fillableCount || forced.length > 0
  return { inlineCount, hasMore }
}

function measureActionWidth(action: AppRowActionMeasure): number {
  if (action.measuredOk && typeof action.measured === 'number' && action.measured > 0) {
    return action.measured
  }
  // 无实测宽度时按文本近似估算，作为纯函数与 jsdom 场景的稳定兜底
  return action.label.length * 14 + 12
}

export type AppRowActionType = 'default' | 'primary' | 'success' | 'warning' | 'danger' | 'info'

export type AppRowActionPlacement = 'auto' | 'inline' | 'more'

export interface AppRowAction {
  key: string
  label: string
  testId?: string
  type?: AppRowActionType
  permission?: string | string[]
  visible?: boolean
  disabled?: boolean
  loading?: boolean
  tooltip?: string
  placement?: AppRowActionPlacement
  onClick?: (event?: MouseEvent) => void
}
