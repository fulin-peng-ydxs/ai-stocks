export const OVERFLOW_AWARE_COLUMN_CLASS = 'app-table-column--overflow-aware'
export const CELL_VISUAL_MEASURED_CLASS = 'app-table-cell--visual-measured'
export const CELL_VISUAL_OVERFLOW_CLASS = 'app-table-cell--visual-overflow'

const GEOMETRY_TOLERANCE_PX = 0.5
const INTRINSIC_VISUAL_TAGS = new Set([
  'BUTTON',
  'CANVAS',
  'IFRAME',
  'IMG',
  'INPUT',
  'METER',
  'PROGRESS',
  'SELECT',
  'TEXTAREA',
  'VIDEO',
])

interface VisualOverflowResult {
  overflow: boolean
}

function rectOverflowsHorizontally(contentRect: DOMRect, cellRect: DOMRect): boolean {
  if (contentRect.width <= 0 || contentRect.height <= 0) return false
  return contentRect.left < cellRect.left - GEOMETRY_TOLERANCE_PX
    || contentRect.right > cellRect.right + GEOMETRY_TOLERANCE_PX
}

function textRects(node: Text): DOMRect[] {
  if (!node.textContent?.trim()) return []
  const range = document.createRange()
  range.selectNodeContents(node)
  if (typeof range.getClientRects === 'function') return Array.from(range.getClientRects())
  return typeof range.getBoundingClientRect === 'function' ? [range.getBoundingClientRect()] : []
}

function hasVisibleColor(value: string): boolean {
  const normalized = value.replaceAll(' ', '').toLowerCase()
  return Boolean(normalized)
    && normalized !== 'transparent'
    && !/^rgba\([^)]*,0(?:\.0+)?\)$/.test(normalized)
}

function hasVisibleBorder(style: CSSStyleDeclaration): boolean {
  return ['Top', 'Right', 'Bottom', 'Left'].some((side) => {
    const borderStyle = style.getPropertyValue(`border-${side.toLowerCase()}-style`)
    const borderWidth = Number.parseFloat(
      style.getPropertyValue(`border-${side.toLowerCase()}-width`),
    )
    const borderColor = style.getPropertyValue(`border-${side.toLowerCase()}-color`)
    return borderStyle !== 'none' && borderWidth > 0 && hasVisibleColor(borderColor)
  })
}

function elementPaintsOwnBox(
  element: HTMLElement | SVGElement,
  style: CSSStyleDeclaration,
): boolean {
  if (element instanceof SVGElement) return true
  if (INTRINSIC_VISUAL_TAGS.has(element.tagName)) return true

  return hasVisibleColor(style.backgroundColor)
    || (Boolean(style.backgroundImage) && style.backgroundImage !== 'none')
    || (Boolean(style.boxShadow) && style.boxShadow !== 'none')
    || hasVisibleBorder(style)
}

function visualRects(cell: HTMLElement): DOMRect[] {
  const rects: DOMRect[] = []
  const visit = (node: Node): void => {
    if (node instanceof Text) {
      rects.push(...textRects(node))
      return
    }
    if (!(node instanceof HTMLElement || node instanceof SVGElement)) return
    const style = getComputedStyle(node)
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return
    if (elementPaintsOwnBox(node, style)) rects.push(node.getBoundingClientRect())
    // 原生省略元素是独立裁切边界，由全局悬浮提示直接接管。不要继续测量其被隐藏的
    // 子文本，否则表格会在胶囊右侧再补一个单元格级省略号。
    if (node instanceof HTMLElement && style.textOverflow.split(/\s+/).includes('ellipsis')) return
    node.childNodes.forEach(visit)
  }
  cell.childNodes.forEach(visit)
  return rects
}

/**
 * 只比较文字和有实际绘制外观的元素矩形与单元格外边界。透明布局容器只负责
 * 递归，不计入内容宽度，也不使用会包含 padding、margin 的 scrollWidth。
 */
export function measureCellVisualOverflow(cell: HTMLElement): VisualOverflowResult {
  const cellRect = cell.getBoundingClientRect()
  if (cellRect.width <= 0) return { overflow: false }

  const overflowingRect = visualRects(cell).find((rect) => (
    rectOverflowsHorizontally(rect, cellRect)
  ))
  return { overflow: Boolean(overflowingRect) }
}

function clearOverflowState(cell: HTMLElement, legacyTooltipClass: string): void {
  cell.classList.remove(
    CELL_VISUAL_MEASURED_CLASS,
    CELL_VISUAL_OVERFLOW_CLASS,
    legacyTooltipClass,
  )
}

export function syncTableCellVisualOverflow(root: HTMLElement): void {
  const legacyTooltipClass = `${root.dataset.prefix || 'el'}-tooltip`
  const awareCells = new Set(root.querySelectorAll<HTMLElement>(
    `.el-table__body td.${OVERFLOW_AWARE_COLUMN_CLASS} > .cell`,
  ))

  root.querySelectorAll<HTMLElement>(
    `.el-table__body .cell.${CELL_VISUAL_MEASURED_CLASS}`,
  ).forEach((cell) => {
    if (!awareCells.has(cell)) clearOverflowState(cell, legacyTooltipClass)
  })

  awareCells.forEach((cell) => {
    const result = measureCellVisualOverflow(cell)
    cell.classList.remove(legacyTooltipClass)
    cell.classList.add(CELL_VISUAL_MEASURED_CLASS)
    cell.classList.toggle(CELL_VISUAL_OVERFLOW_CLASS, result.overflow)
  })
}
