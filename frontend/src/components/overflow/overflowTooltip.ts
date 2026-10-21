import {
  ACTION_COLUMN_CLASS,
  CELL_VISUAL_OVERFLOW_CLASS,
  textClientRects,
} from '@/components/table/cellVisualOverflow'

const OVERFLOW_TOLERANCE_PX = 0.5
// 盒边界与文字坐标分别取整，容忍两个布局精度单位的差值，仍保留亚像素截断检测。
const TEXT_GEOMETRY_EPSILON_PX = 1 / 32
const OVERFLOW_TOOLTIP_DELEGATE_SELECTOR = '[data-overflow-tooltip-delegate]'
const OVERFLOW_TOOLTIP_TARGET_SELECTOR = '[data-overflow-tooltip-target]'
const AUTO_DELEGATE_INTERACTIVE_SELECTOR = [
  'button',
  'a',
  '[role="button"]',
  '[role="link"]',
  '[role="option"]',
  '[role="tab"]',
].join(',')
const OVERFLOW_TOOLTIP_EXCLUSION_SELECTOR = [
  '[data-overflow-tooltip-disabled]',
  '.el-tooltip__trigger',
  `.${ACTION_COLUMN_CLASS}`,
].join(',')
const DESCRIBED_INTERACTIVE_SELECTOR = [
  'button[aria-describedby]',
  'a[aria-describedby]',
  'input[aria-describedby]',
  'select[aria-describedby]',
  'textarea[aria-describedby]',
  '[role="button"][aria-describedby]',
  '[role="link"][aria-describedby]',
  '[role="checkbox"][aria-describedby]',
  '[role="radio"][aria-describedby]',
  '[role="switch"][aria-describedby]',
  '[role="tab"][aria-describedby]',
].join(',')

export function isNativeEllipsisOverflow(element: HTMLElement): boolean {
  const style = getComputedStyle(element)
  if (!style.textOverflow.split(/\s+/).includes('ellipsis')) return false
  // text-overflow 本身不会裁切内容；表格 td 等容器也可能声明它，但实际 overflow
  // 为 visible。不能把这些祖先节点的布局矩形当成被省略的文字。
  const overflowX = style.overflowX || style.overflow.split(/\s+/)[0]
  if (!['hidden', 'clip', 'auto', 'scroll'].includes(overflowX)) return false
  // 单行省略只发生在横向；字体行盒取整可能让 scrollHeight 略高，不能据此弹出重复提示。
  if (element.scrollWidth > element.clientWidth + OVERFLOW_TOLERANCE_PX) return true

  // Chrome 在 zoom 下可能已经绘制省略号，但整数 scrollWidth/clientWidth 仍相等。
  // 用既有 Range 测量补足亚像素差值；统一比较视口坐标，扣除边框和内边距。
  const box = element.getBoundingClientRect()
  if (box.width <= 0 || box.height <= 0) return false
  const px = (value: string) => Number.parseFloat(value) || 0
  const leftInset = px(style.borderLeftWidth) + px(style.paddingLeft)
  const rightInset = px(style.borderRightWidth) + px(style.paddingRight)
  const layoutWidth = px(style.width)
    + (style.boxSizing === 'border-box' ? 0 : leftInset + rightInset)
  if (layoutWidth <= 0) return false
  const scale = box.width / layoutWidth
  const left = box.left + leftInset * scale
  const right = box.right - rightInset * scale
  const epsilon = TEXT_GEOMETRY_EPSILON_PX * scale
  return textClientRects(element).some(rect => rect.width > 0 && rect.height > 0
    && (rect.left < left - epsilon || rect.right > right + epsilon))
}

function isWithinTooltipExclusion(element: HTMLElement): boolean {
  return Boolean(
    element.closest(OVERFLOW_TOOLTIP_EXCLUSION_SELECTOR)
    || element.closest(DESCRIBED_INTERACTIVE_SELECTOR),
  )
}

function delegatedOverflowTarget(element: HTMLElement): HTMLElement | null {
  if (element.matches(OVERFLOW_TOOLTIP_DELEGATE_SELECTOR)) {
    return Array.from(element.querySelectorAll<HTMLElement>(OVERFLOW_TOOLTIP_TARGET_SELECTOR))
      .find(isNativeEllipsisOverflow) ?? null
  }
  if (!element.matches(AUTO_DELEGATE_INTERACTIVE_SELECTOR)) return null
  const labels = Array.from(element.querySelectorAll<HTMLElement>('*'))
    .filter(label => getComputedStyle(label).textOverflow.split(/\s+/).includes('ellipsis'))
  // 只代理单一标签控件；复合摘要即使当下只有一段截断，也应按各段文字分别提示。
  return labels.length === 1 && isNativeEllipsisOverflow(labels[0]) ? labels[0] : null
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
    // 复合按钮的事件可能命中文字外的内边距或图标；由容器显式代理到真实省略文本，
    // 仍以文本节点实际发生截断为前提，不把整个按钮误判为溢出。
    const delegated = delegatedOverflowTarget(element)
    if (delegated) return delegated
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
    || element.textContent
    || element.getAttribute('aria-label')
    || ''
  )
    .replace(/\s+/g, ' ')
    .trim()
}
