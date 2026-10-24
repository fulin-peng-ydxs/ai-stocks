import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { parse as parseSfc } from '@vue/compiler-sfc'
import postcss from 'postcss'

function declaration(file: string, selector: string, property: string): string | undefined {
  const source = readFileSync(resolve(process.cwd(), 'src', file), 'utf8')
  const css = file.endsWith('.vue')
    ? parseSfc(source).descriptor.styles.map(style => style.content).join('\n')
    : source
  let value: string | undefined
  postcss.parse(css).walkRules(rule => {
    if (rule.selectors.includes(selector)) {
      rule.walkDecls(property, decl => { value = decl.value })
    }
  })
  return value
}

describe('交互呈现的共享尺寸契约', () => {
  it('命令、输入、选择、图标命令及工具栏共同消费常规密度', () => {
    const inherited = 'var(--app-density-control-height, var(--app-control-height-md))'
    const consumers = [
      ['styles/global.css', ':root', '--el-component-size'],
      ['styles/global.css', 'html[data-layout-preset] .el-button', 'height'],
      ['components/PageSegmented.vue', '.page-segmented', 'height'],
      ['components/AppSelect.vue', '.app-select', '--app-select-control-height'],
      ['components/AppFilterSelect.vue', '.app-filter-select__control :deep(.el-select__wrapper)', 'height'],
      ['components/AppIconButton.vue', '.app-icon-button', '--app-icon-button-size'],
      ['components/AppTabToolbar.vue', '.app-tab-toolbar', 'min-height'],
    ]
    for (const [file, selector, property] of consumers) {
      expect(declaration(file, selector, property), `${file} ${selector}`).toBe(inherited)
    }
  })

  it.each([
    ['small', 'sm'],
    ['large', 'lg'],
  ])('显式 %s 在命令、输入与选择中映射同一个档位', (size, token) => {
    const expected = `var(--app-control-height-${token})`
    expect(declaration('styles/global.css', ':root', `--el-component-size-${size}`)).toBe(expected)
    expect(declaration('styles/global.css', `html[data-layout-preset] .el-button.el-button--${size}`, 'height')).toBe(expected)
    expect(declaration('components/PageSegmented.vue', `.page-segmented--${size}`, 'height')).toBe(expected)
    expect(declaration('components/AppSelect.vue', `.app-select.el-select--${size}`, '--app-select-control-height')).toBe(expected)
    expect(declaration('components/AppFilterSelect.vue', `.app-filter-select--${size} .app-filter-select__control :deep(.el-select__wrapper)`, 'height')).toBe(expected)
  })

  it('选择器适配同时约束库的最小高度，避免高度变量被固定最小值顶回去', () => {
    expect(declaration('components/AppSelect.vue', '.app-select :deep(.el-select__wrapper)', 'min-height'))
      .toBe('var(--app-select-control-height)')
    expect(declaration('components/AppSelect.vue', '.app-select :deep(.el-select__wrapper)', 'padding-block'))
      .toBe('0')
  })
})
