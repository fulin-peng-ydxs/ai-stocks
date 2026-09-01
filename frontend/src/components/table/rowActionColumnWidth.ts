import type { InjectionKey } from 'vue'

/**
 * 行操作组向所属操作列登记最低宽度的内部协议。
 * 每一行使用独立 source，列组件据此取当前所有已渲染行的最大需求。
 */
export interface RowActionColumnWidthContext {
  setMinimumWidth: (source: symbol, width: number) => void
  removeMinimumWidth: (source: symbol) => void
}

export const ROW_ACTION_COLUMN_WIDTH_CONTEXT: InjectionKey<RowActionColumnWidthContext> =
  Symbol('row-action-column-width')
