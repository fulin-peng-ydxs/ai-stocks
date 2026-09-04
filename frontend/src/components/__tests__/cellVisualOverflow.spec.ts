// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import {
  CELL_VISUAL_MEASURED_CLASS,
  CELL_VISUAL_OVERFLOW_CLASS,
  OVERFLOW_AWARE_COLUMN_CLASS,
  measureCellVisualOverflow,
  syncTableCellVisualOverflow,
} from '@/components/table/cellVisualOverflow'

function rect(left: number, width: number, top = 0, height = 24): DOMRect {
  return {
    bottom: top + height,
    height,
    left,
    right: left + width,
    top,
    width,
    x: left,
    y: top,
    toJSON: () => ({}),
  }
}

function createAwareCell(content: string): { root: HTMLElement; cell: HTMLElement } {
  const root = document.createElement('div')
  root.dataset.prefix = 'el'
  root.innerHTML = `
    <table class="el-table__body"><tbody><tr>
      <td class="el-table__cell ${OVERFLOW_AWARE_COLUMN_CLASS}">
        <div class="cell">${content}</div>
      </td>
    </tr></tbody></table>
  `
  return { root, cell: root.querySelector<HTMLElement>('.cell')! }
}

describe('表格内容视觉溢出判定', () => {
  it('可见内容未越界时忽略 padding 造成的虚假 scrollWidth', () => {
    const { root, cell } = createAwareCell(`
      <div class="transparent-layout">
        <span class="el-tag" style="border: 1px solid red">主升浪核心</span>
      </div>
    `)
    const layout = cell.querySelector<HTMLElement>('.transparent-layout')!
    const tag = cell.querySelector<HTMLElement>('.el-tag')!
    Object.defineProperty(cell, 'scrollWidth', { value: 105 })
    Object.defineProperty(cell, 'clientWidth', { value: 96 })
    cell.getBoundingClientRect = () => rect(0, 96)
    layout.getBoundingClientRect = () => rect(12, 100)
    tag.getBoundingClientRect = () => rect(12, 81)

    syncTableCellVisualOverflow(root)

    expect(cell.classList.contains(CELL_VISUAL_MEASURED_CLASS)).toBe(true)
    expect(cell.classList.contains(CELL_VISUAL_OVERFLOW_CLASS)).toBe(false)
    expect(cell.classList.contains('el-tooltip')).toBe(false)
  })

  it('递归识别复合内容中真正越过单元格边界的子项', () => {
    const { root, cell } = createAwareCell(`
      <div class="subchips">
        <span class="subchip" style="border: 1px solid red">放量突破(固定20×2)100</span>
      </div>
    `)
    const group = cell.querySelector<HTMLElement>('.subchips')!
    const chip = cell.querySelector<HTMLElement>('.subchip')!
    cell.getBoundingClientRect = () => rect(0, 140, 10, 132)
    group.getBoundingClientRect = () => rect(12, 116, 10, 132)
    chip.getBoundingClientRect = () => rect(12, 156, 54, 22)

    expect(measureCellVisualOverflow(cell)).toEqual({ overflow: true })
    syncTableCellVisualOverflow(root)

    expect(cell.classList.contains(CELL_VISUAL_OVERFLOW_CLASS)).toBe(true)
    expect(cell.classList.contains('el-tooltip')).toBe(false)
  })

  it('原生省略胶囊作为独立裁切边界，不再触发表格第二个省略号', () => {
    const { cell } = createAwareCell(`
      <span class="subchip" style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
        放量突破(固定20×2)100
      </span>
    `)
    const chip = cell.querySelector<HTMLElement>('.subchip')!
    cell.getBoundingClientRect = () => rect(0, 140)
    chip.getBoundingClientRect = () => rect(12, 116)

    expect(measureCellVisualOverflow(cell)).toEqual({ overflow: false })
  })

  it('列退出统一溢出机制后清理残留状态', () => {
    const { root, cell } = createAwareCell('<span>普通内容</span>')
    cell.classList.add(CELL_VISUAL_MEASURED_CLASS, CELL_VISUAL_OVERFLOW_CLASS, 'el-tooltip')
    cell.parentElement?.classList.remove(OVERFLOW_AWARE_COLUMN_CLASS)

    syncTableCellVisualOverflow(root)

    expect(cell.classList.contains(CELL_VISUAL_MEASURED_CLASS)).toBe(false)
    expect(cell.classList.contains(CELL_VISUAL_OVERFLOW_CLASS)).toBe(false)
    expect(cell.classList.contains('el-tooltip')).toBe(false)
  })
})
