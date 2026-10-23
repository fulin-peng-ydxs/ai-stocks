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
