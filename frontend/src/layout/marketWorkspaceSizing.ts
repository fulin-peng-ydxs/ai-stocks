/** 行情主从工作台的可阅读高度契约，供运行时组件与页面布局登记共同消费。 */
export const MARKET_WORKSPACE_MIN_HEIGHT = 480
export const MARKET_WORKSPACE_COMPACT_MIN_HEIGHT = 400

export type MarketWorkspaceHeightMode = 'fill' | 'adaptive'

/**
 * 自适应工作台占满滚动容器当前内容位置之后的剩余空间；空间不足时守住可读下限，
 * 由外层滚动容器承接页面滚动，工作台内部继续负责列表与图表滚动。
 */
export function adaptiveWorkspaceHeight(options: {
  scrollportHeight: number
  contentTop: number
  minHeight: number
  bottomInset?: number
}): number {
  const available = options.scrollportHeight - options.contentTop - (options.bottomInset ?? 0)
  return Math.max(options.minHeight, Math.round(available))
}
