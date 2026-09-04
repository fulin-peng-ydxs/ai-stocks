// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import {
  CELL_VISUAL_CONTENT_FITS_CLASS,
  syncTagCellVisualOverflow,
} from '@/components/table/cellVisualOverflow'

function rect(left: number, width: number): DOMRect {
  return {
    bottom: 24,
    height: 24,
    left,
    right: left + width,
    top: 0,
    width,
    x: left,
    y: 0,
    toJSON: () => ({}),
  }
}

function createTagCell(): { root: HTMLElement; cell: HTMLElement; tag: HTMLElement } {
  const root = document.createElement('div')
  root.innerHTML = `
    <table class="el-table__body">
      <tbody><tr><td class="el-table__cell"><div class="cell">
        <span class="el-tag">主升浪核心</span>
      </div></td></tr></tbody>
    </table>
  `
  return {
    root,
    cell: root.querySelector<HTMLElement>('.cell')!,
    tag: root.querySelector<HTMLElement>('.el-tag')!,
  }
}

describe('表格标签视觉溢出判定', () => {
  it('标签本体未越过单元格边界时忽略 padding 造成的虚假 scrollWidth', () => {
    const { root, cell, tag } = createTagCell()
    Object.defineProperty(cell, 'scrollWidth', { value: 104 })
    Object.defineProperty(cell, 'clientWidth', { value: 96 })
    cell.getBoundingClientRect = () => rect(0, 96)
    tag.getBoundingClientRect = () => rect(12, 80)

    syncTagCellVisualOverflow(root)

    expect(cell.classList.contains(CELL_VISUAL_CONTENT_FITS_CLASS)).toBe(true)
  })

  it('标签本体真正越过单元格边界时保留溢出表现', () => {
    const { root, cell, tag } = createTagCell()
    cell.classList.add(CELL_VISUAL_CONTENT_FITS_CLASS)
    cell.getBoundingClientRect = () => rect(0, 96)
    tag.getBoundingClientRect = () => rect(12, 88)

    syncTagCellVisualOverflow(root)

    expect(cell.classList.contains(CELL_VISUAL_CONTENT_FITS_CLASS)).toBe(false)
  })

  it('普通文字或复合内容不进入标签专用修正', () => {
    const { root, cell, tag } = createTagCell()
    tag.classList.remove('el-tag')
    cell.classList.add(CELL_VISUAL_CONTENT_FITS_CLASS)

    syncTagCellVisualOverflow(root)

    expect(cell.classList.contains(CELL_VISUAL_CONTENT_FITS_CLASS)).toBe(false)
  })
})
