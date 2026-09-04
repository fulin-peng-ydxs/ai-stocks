// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest'
import {
  findOverflowTooltipTarget,
  isNativeEllipsisOverflow,
  overflowTooltipContent,
} from '@/components/overflow/overflowTooltip'
import { CELL_VISUAL_OVERFLOW_CLASS } from '@/components/table/cellVisualOverflow'

function setBox(element: HTMLElement, clientWidth: number, scrollWidth: number): void {
  Object.defineProperty(element, 'clientWidth', { value: clientWidth, configurable: true })
  Object.defineProperty(element, 'scrollWidth', { value: scrollWidth, configurable: true })
}

afterEach(() => {
  document.body.innerHTML = ''
})

describe('全局省略悬浮目标判定', () => {
  it('只识别真实发生截断的 CSS 省略元素', () => {
    const element = document.createElement('span')
    element.style.textOverflow = 'ellipsis'
    element.style.overflow = 'hidden'
    setBox(element, 100, 100)
    expect(isNativeEllipsisOverflow(element)).toBe(false)

    setBox(element, 100, 140)
    expect(isNativeEllipsisOverflow(element)).toBe(true)
  })

  it('从子节点命中最近的省略元素并自动读取完整文本', () => {
    document.body.innerHTML = `
      <span id="chip" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
        放量突破 <b>100</b>
      </span>
    `
    const chip = document.querySelector<HTMLElement>('#chip')!
    setBox(chip, 80, 140)

    expect(findOverflowTooltipTarget(chip.querySelector('b'))).toBe(chip)
    expect(overflowTooltipContent(chip)).toBe('放量突破 100')
  })

  it('复用表格视觉溢出标记，并跳过已有业务 popover 的内容', () => {
    const tableCell = document.createElement('div')
    tableCell.className = CELL_VISUAL_OVERFLOW_CLASS
    tableCell.textContent = '完整表格内容'
    document.body.append(tableCell)
    expect(findOverflowTooltipTarget(tableCell)).toBe(tableCell)

    const disclosed = document.createElement('span')
    disclosed.className = 'el-tooltip__trigger'
    disclosed.style.textOverflow = 'ellipsis'
    setBox(disclosed, 40, 100)
    document.body.append(disclosed)
    expect(findOverflowTooltipTarget(disclosed)).toBeNull()
  })

  it('无文本节点的输入值和既有 title 也复用统一提示内容', () => {
    const input = document.createElement('input')
    input.value = '被截断的输入值'
    expect(overflowTooltipContent(input)).toBe('被截断的输入值')

    const titled = document.createElement('span')
    titled.title = '完整说明'
    expect(overflowTooltipContent(titled)).toBe('完整说明')
  })

  it('表格标签在自身内容末尾使用原生省略并接入统一悬浮', () => {
    document.body.innerHTML = `
      <div class="app-data-table">
        <table><tbody><tr>
          <td class="app-table-column--overflow-aware">
            <div class="cell">
              <span class="el-tag"><span id="tag-content" class="el-tag__content">依赖·长任务名称</span></span>
            </div>
          </td>
        </tr></tbody></table>
      </div>
    `
    const tag = document.querySelector<HTMLElement>('.el-tag')!
    const content = document.querySelector<HTMLElement>('#tag-content')!
    content.style.overflow = 'hidden'
    content.style.textOverflow = 'ellipsis'
    setBox(content, 72, 140)

    expect(tag.classList.contains('el-tag')).toBe(true)
    expect(getComputedStyle(content).textOverflow).toBe('ellipsis')
    expect(findOverflowTooltipTarget(content)).toBe(content)
  })
})
