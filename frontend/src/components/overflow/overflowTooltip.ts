import { CELL_VISUAL_OVERFLOW_CLASS } from '@/components/table/cellVisualOverflow'

const OVERFLOW_TOLERANCE_PX = 0.5
const EXISTING_DISCLOSURE_SELECTOR = [
  '[data-overflow-tooltip-disabled]',
  '.el-tooltip__trigger',
  '[aria-describedby]',
].join(',')

export function isNativeEllipsisOverflow(element: HTMLElement): boolean {
  const style = getComputedStyle(element)
  if (!style.textOverflow.split(/\s+/).includes('ellipsis')) return false
  return element.scrollWidth > element.clientWidth + OVERFLOW_TOLERANCE_PX
    || element.scrollHeight > element.clientHeight + OVERFLOW_TOLERANCE_PX
}

function hasExistingDisclosure(element: HTMLElement): boolean {
  return Boolean(element.closest(EXISTING_DISCLOSURE_SELECTOR))
}

/**
 * 从事件命中的最内层节点向外寻找真实截断目标。原生 CSS 省略和表格复合内容
 * 的视觉溢出标记共用这一入口；已有 popover/tooltip 的业务内容不会重复提示。
 */
export function findOverflowTooltipTarget(target: EventTarget | null): HTMLElement | null {
  if (!(target instanceof Node)) return null
  let element = target instanceof HTMLElement ? target : target.parentElement
  while (element && element !== document.documentElement) {
    const overflowed = element.classList.contains(CELL_VISUAL_OVERFLOW_CLASS)
      || isNativeEllipsisOverflow(element)
    if (overflowed && !hasExistingDisclosure(element)) return element
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
