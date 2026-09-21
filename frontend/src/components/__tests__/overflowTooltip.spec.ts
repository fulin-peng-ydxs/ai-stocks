// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest'
import {
  findOverflowTooltipTarget,
  isNativeEllipsisOverflow,
  overflowTooltipContent,
} from '@/components/overflow/overflowTooltip'
import {
  ACTION_COLUMN_CLASS,
  CELL_VISUAL_OVERFLOW_CLASS,
} from '@/components/table/cellVisualOverflow'

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

    Object.defineProperty(element, 'clientHeight', { value: 20, configurable: true })
    Object.defineProperty(element, 'scrollHeight', { value: 21, configurable: true })
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

  it('复合按钮命中内边距时代理到内部真实省略文本', () => {
    document.body.innerHTML = `
      <button id="segmented-option" data-overflow-tooltip-delegate>
        <span id="segmented-label" data-overflow-tooltip-target
          style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
          逐股分层体检
        </span>
      </button>
    `
    const button = document.querySelector<HTMLElement>('#segmented-option')!
    const label = document.querySelector<HTMLElement>('#segmented-label')!
    setBox(label, 72, 112)

    expect(findOverflowTooltipTarget(button)).toBe(label)
    expect(overflowTooltipContent(label)).toBe('逐股分层体检')
  })

  it('对话框的 aria-describedby 不会误伤内部省略提示', () => {
    document.body.innerHTML = `
      <div role="dialog" aria-describedby="drawer-description">
        <button id="segmented-option" data-overflow-tooltip-delegate>
          <span id="segmented-label" data-overflow-tooltip-target
            style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
            逐股分层体检
          </span>
        </button>
      </div>
    `
    const button = document.querySelector<HTMLElement>('#segmented-option')!
    const label = document.querySelector<HTMLElement>('#segmented-label')!
    setBox(label, 72, 112)

    expect(findOverflowTooltipTarget(button)).toBe(label)

    button.setAttribute('aria-describedby', 'existing-tooltip')
    expect(findOverflowTooltipTarget(button)).toBeNull()
  })

  it('后续简单交互控件自动代理唯一的内部省略文本', () => {
    document.body.innerHTML = `
      <div id="rule" role="option" tabindex="0">
        <span id="rule-name" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
          很长的交易纪律规则名称
        </span>
      </div>
      <button id="complex-card">
        <strong id="complex-title" style="overflow:hidden;text-overflow:ellipsis">很长的标题</strong>
        <small id="complex-preview" style="overflow:hidden;text-overflow:ellipsis">很长的摘要</small>
      </button>
    `
    const rule = document.querySelector<HTMLElement>('#rule')!
    const ruleName = document.querySelector<HTMLElement>('#rule-name')!
    const complexCard = document.querySelector<HTMLElement>('#complex-card')!
    const complexTitle = document.querySelector<HTMLElement>('#complex-title')!
    const complexPreview = document.querySelector<HTMLElement>('#complex-preview')!
    setBox(ruleName, 80, 160)
    setBox(complexTitle, 80, 160)
    setBox(complexPreview, 80, 160)

    expect(findOverflowTooltipTarget(rule)).toBe(ruleName)
    expect(findOverflowTooltipTarget(complexCard)).toBeNull()
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

  it('操作列和动作组不会被单元格原生省略拼成通用悬浮内容', () => {
    document.body.innerHTML = `
      <td class="${ACTION_COLUMN_CLASS}">
        <div id="action-cell" class="cell" style="overflow:hidden;text-overflow:ellipsis">
          <div data-overflow-tooltip-disabled>
            <button id="run-action">立即执行</button>
            <span aria-hidden="true">立即执行编辑触发记录删除更多</span>
          </div>
        </div>
      </td>
    `
    const cell = document.querySelector<HTMLElement>('#action-cell')!
    const button = document.querySelector<HTMLElement>('#run-action')!
    setBox(cell, 140, 320)

    expect(isNativeEllipsisOverflow(cell)).toBe(true)
    expect(findOverflowTooltipTarget(button)).toBeNull()
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
