export const CELL_VISUAL_CONTENT_FITS_CLASS = 'app-table-cell--visual-content-fits'

const GEOMETRY_TOLERANCE_PX = 0.5

function isInsideHorizontalBounds(contentRect: DOMRect, cellRect: DOMRect): boolean {
  return contentRect.left >= cellRect.left - GEOMETRY_TOLERANCE_PX
    && contentRect.right <= cellRect.right + GEOMETRY_TOLERANCE_PX
}

/**
 * Element Plus 的 `.cell` 会把透明 padding 计入 scrollWidth，可能在标签本体仍位于
 * 单元格边界内时绘制省略号。这里仅按可见标签的真实边界修正该状态。
 */
export function syncTagCellVisualOverflow(root: HTMLElement): void {
  const cells = root.querySelectorAll<HTMLElement>(
    '.el-table__body td.el-table__cell > .cell',
  )

  cells.forEach((cell) => {
    const elementChildren = Array.from(cell.children)
    const tag = elementChildren.length === 1 && elementChildren[0].classList.contains('el-tag')
      ? elementChildren[0] as HTMLElement
      : null

    if (!tag) {
      cell.classList.remove(CELL_VISUAL_CONTENT_FITS_CLASS)
      return
    }

    cell.classList.toggle(
      CELL_VISUAL_CONTENT_FITS_CLASS,
      isInsideHorizontalBounds(tag.getBoundingClientRect(), cell.getBoundingClientRect()),
    )
  })
}
