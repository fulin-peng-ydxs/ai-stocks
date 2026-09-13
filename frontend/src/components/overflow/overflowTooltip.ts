import {
  ACTION_COLUMN_CLASS,
  CELL_VISUAL_OVERFLOW_CLASS,
} from '@/components/table/cellVisualOverflow'

const OVERFLOW_TOLERANCE_PX = 0.5
const OVERFLOW_TOOLTIP_EXCLUSION_SELECTOR = [
  '[data-overflow-tooltip-disabled]',
  '.el-tooltip__trigger',
  '[aria-describedby]',
  `.${ACTION_COLUMN_CLASS}`,
].join(',')

export function isNativeEllipsisOverflow(element: HTMLElement): boolean {
  const style = getComputedStyle(element)
  if (!style.textOverflow.split(/\s+/).includes('ellipsis')) return false
  // 单行省略只发生在横向；字体行盒取整可能让 scrollHeight 略高，不能据此弹出重复提示。
  return element.scrollWidth > element.clientWidth + OVERFLOW_TOLERANCE_PX
}

function isWithinTooltipExclusion(element: HTMLElement): boolean {
  return Boolean(element.closest(OVERFLOW_TOOLTIP_EXCLUSION_SELECTOR))
}

/**
 * 从事件命中的最内层节点向外寻找真实截断目标。原生 CSS 省略和表格复合内容
 * 的视觉溢出标记共用这一入口；已有 popover/tooltip 的业务内容不会重复提示。
 */
export function findOverflowTooltipTarget(target: EventTarget | null): HTMLElement | null {
  if (!(target instanceof Node)) return null
  let element = target instanceof HTMLElement ? target : target.parentElement
  // 操作组、操作列和已有说明浮层是完整的交互边界。命中边界后不得继续向上
  // 把 Element Plus 单元格及隐藏测量副本拼成普通文本提示。
  if (element && isWithinTooltipExclusion(element)) return null
  while (element && element !== document.documentElement) {
    const overflowed = element.classList.contains(CELL_VISUAL_OVERFLOW_CLASS)
      || isNativeEllipsisOverflow(element)
    if (overflowed) return element
    element = element.parentElement
  }
  return null
}

export function overflowTooltipContent(element: HTMLElement): string {
  const formValue = element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement
    ? element.value
    : ''
  return (
    element.dataset.overflowTooltipContent
    || formValue
    || element.title
    || element.textContent
    || element.getAttribute('aria-label')
    || ''
  )
    .replace(/\s+/g, ' ')
    .trim()
}
