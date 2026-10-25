// @vitest-environment jsdom
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, beforeEach, expect, it } from 'vitest'

let style: HTMLStyleElement
let fixture: HTMLDivElement
let previousPreset: string | null
beforeEach(() => {
  style = document.createElement('style')
  style.textContent = readFileSync(resolve(process.cwd(), 'src/styles/borders.css'), 'utf8')
  document.head.append(style)
  fixture = document.createElement('div')
  document.body.append(fixture)
  previousPreset = document.documentElement.getAttribute('data-layout-preset')
  document.documentElement.dataset.layoutPreset = 'balanced'
})
afterEach(() => {
  style.remove()
  fixture.remove()
  if (previousPreset === null) delete document.documentElement.dataset.layoutPreset
  else document.documentElement.setAttribute('data-layout-preset', previousPreset)
})

it('浮层圆角由 tooltip/popover/menu 角色决定，深浅底色不改变角色', () => {
  for (const [classes, role] of [
    ['el-popper is-light app-hover-info--tooltip', 'control'],
    ['el-popper is-dark app-hover-info--tooltip', 'control'],
    ['el-popper is-dark', 'control'],
    ['el-popper is-dark el-popover', 'card'],
    ['el-popper is-dark el-dropdown__popper', 'card'],
    ['el-popper is-dark app-hover-info--popover', 'card'],
  ]) {
    const popper = document.createElement('div')
    popper.className = classes
    fixture.append(popper)
    expect(getComputedStyle(popper).borderRadius, classes).toBe(`var(--layout-${role}-radius)`)
    popper.remove()
  }
})

it('输入错误焦点保留错误语义，禁用覆盖错误焦点且保留中性边界', () => {
  for (const [content, error, border] of [
    ['<div class="el-range-editor el-input__wrapper is-active" data-field></div>', false, '--app-border-selected'],
    ['<div class="el-range-editor el-input__wrapper is-active" data-field></div>', true, '--el-color-danger'],
    ['<div class="el-range-editor el-input__wrapper is-active is-disabled" data-field></div>', true, '--el-disabled-border-color'],
    ['<div class="el-input is-disabled"><div class="el-input__wrapper is-focus" data-field></div></div>', true, '--el-disabled-border-color'],
    ['<div class="el-textarea is-disabled"><textarea class="el-textarea__inner" data-field></textarea></div>', true, '--el-disabled-border-color'],
    ['<div class="el-select__wrapper is-focused is-disabled" data-field></div>', true, '--el-disabled-border-color'],
  ] as const) {
    fixture.innerHTML = `<div class="el-form-item ${error ? 'is-error' : ''}">${content}</div>`
    const field = fixture.querySelector<HTMLElement>('[data-field]')!
    expect(getComputedStyle(field).boxShadow, content).toContain(`var(${border})`)
  }
})

it('真实库按钮组在中间项选中与禁用时没有普通 outline 或负向补线残留', () => {
  // 加载实际依赖 CSS，防止库从 border 改成 outline 后只测项目声明而漏掉冲突。
  style.textContent = ['radio', 'checkbox'].map(kind => readFileSync(resolve(
    process.cwd(), `node_modules/element-plus/theme-chalk/el-${kind}-button.css`,
  ), 'utf8')).join('\n') + style.textContent
  for (const kind of ['radio', 'checkbox']) {
    const selected = kind === 'radio' ? 'is-active' : 'is-checked'
    const original = kind === 'radio' ? 'original-radio' : 'original'
    fixture.innerHTML = `<div class="el-${kind}-group">${['is-disabled', selected, ''].map(state =>
      `<label class="el-${kind}-button ${state}"><input type="${kind}" class="el-${kind}-button__${original}" ${state === 'is-disabled' ? 'disabled' : ''}>
        <span class="el-${kind}-button__inner">选项</span></label>`,
    ).join('')}</div>`
    const items = fixture.querySelectorAll<HTMLElement>(`.el-${kind}-button__inner`)
    for (const item of items) {
      expect(getComputedStyle(item).outline, `${kind}: ${item.parentElement!.className}`).toBe('none')
      expect(getComputedStyle(item).boxShadow).toBe('none')
    }
    expect(getComputedStyle(items[1]).zIndex).toBe('1')
    items[1].parentElement!.classList.add('is-disabled')
    items[1].previousElementSibling!.setAttribute('disabled', '')
    expect(getComputedStyle(items[1]).boxShadow).toBe('none')
  }
})
