import type { InjectionKey, Ref } from 'vue'

/**
 * 行操作组向所属操作列登记最低宽度的内部协议。
 * 每一行使用独立 source，列组件据此取当前所有已渲染行的最大需求。
 */
export interface RowActionColumnWidthContext {
  /** 固定操作列的响应式宽度，避免 DOM 尺寸通知滞后造成折叠结果与列宽脱节。 */
  width: Readonly<Ref<number | undefined>>
  setMinimumWidth: (source: symbol, width: number) => void
  removeMinimumWidth: (source: symbol) => void
}

export const ROW_ACTION_COLUMN_WIDTH_CONTEXT: InjectionKey<RowActionColumnWidthContext> =
  Symbol('row-action-column-width')
