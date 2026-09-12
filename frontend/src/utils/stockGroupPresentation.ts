import type { CSSProperties } from 'vue'

export const DEFAULT_STOCK_GROUP_COLOR = '#73757d'

export const STOCK_GROUP_COLOR_PRESETS = [
  '#f66055',
  '#f58a07',
  '#1677ff',
  '#0ea968',
  DEFAULT_STOCK_GROUP_COLOR,
  '#b882ff',
]

/** 股票分组在列表、选择器和详情上下文中共用同一轻量标签色。 */
export function stockGroupTagStyle(color?: string | null): CSSProperties {
  const resolved = color || DEFAULT_STOCK_GROUP_COLOR
  return {
    color: resolved,
    borderColor: resolved,
    backgroundColor: `${resolved}14`,
  }
}
