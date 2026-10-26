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
    const density = 'var(--app-density-control-height, var(--app-control-height-md))'
    const inherited = `var(--app-control-row-height, ${density})`
    const consumers = [

      ['styles/global.css', 'html[data-layout-preset] .el-button', 'height'],
      ['components/PageSegmented.vue', '.page-segmented', 'height'],
      ['components/AppSelect.vue', '.app-select', '--app-select-control-height'],


      ['styles/global.css', 'html[data-layout-preset] .el-radio-button', '--app-choice-control-height'],
      ['styles/global.css', 'html[data-layout-preset] .el-checkbox-button', '--app-choice-control-height'],
      ['styles/global.css', 'html[data-layout-preset] .el-segmented:not(.el-segmented--vertical)', '--app-choice-control-height'],
    ]
    expect(declaration('styles/global.css', ':root', '--el-component-size')).toBe(density)
    expect(declaration('components/AppIconButton.vue', '.app-icon-button', 'height'))
      .toBe('var(--app-control-row-height, var(--app-icon-button-size))')
    expect(declaration('components/AppTabToolbar.vue', '.app-tab-toolbar', 'min-height'))
      .toBe('var(--app-control-row-height)')
    for (const [file, selector, property] of consumers) {
      expect(declaration(file, selector, property), `${file} ${selector}`).toBe(inherited)
    }
  })

  it.each([
    ['small', 'sm'],
    ['large', 'lg'],
  ])('显式 %s 在命令、输入与选择中映射同一个档位', (size, token) => {
    const tokenHeight = `var(--app-control-height-${token})`
    const expected = `var(--app-control-row-height, ${tokenHeight})`
    expect(declaration('styles/global.css', ':root', `--el-component-size-${size}`)).toBe(tokenHeight)
    expect(declaration('styles/global.css', `html[data-layout-preset] .el-button.el-button--${size}`, 'height')).toBe(expected)
    expect(declaration('components/PageSegmented.vue', `.page-segmented--${size}`, 'height')).toBe(expected)
    expect(declaration('components/AppSelect.vue', `.app-select.el-select--${size}`, '--app-select-control-height')).toBe(expected)
    expect(declaration('components/AppSelect.vue', '.app-select--single-line :deep(.el-select__wrapper)', 'height'))
      .toBe('var(--app-select-control-height)')
    for (const kind of ['radio-button', 'checkbox-button', 'segmented']) {
      const selector = `html[data-layout-preset] .el-${kind}--${size}${kind === 'segmented' ? ':not(.el-segmented--vertical)' : ''}`
      expect(declaration('styles/global.css', selector, '--app-choice-control-height')).toBe(expected)
    }
  })

  it('选择器适配同时约束库的最小高度，避免高度变量被固定最小值顶回去', () => {
    expect(declaration('components/AppSelect.vue', '.app-select :deep(.el-select__wrapper)', 'min-height'))
      .toBe('var(--app-select-control-height)')
    expect(declaration('components/AppSelect.vue', '.app-select :deep(.el-select__wrapper)', 'padding-block'))
      .toBe('0')
  })

  it('选择按钮消除库的纵向 padding，库分段同时覆盖固定最小高度，卡片选项保留自然高度', () => {
    for (const kind of ['radio', 'checkbox']) {
      const selector = `html[data-layout-preset] .el-${kind}-button__inner`
      expect(declaration('styles/global.css', selector, 'height')).toBe('var(--app-choice-control-height)')
      expect(declaration('styles/global.css', selector, 'padding-block')).toBe('var(--app-choice-padding-block, 0)')
      expect(declaration('styles/global.css', selector, 'font-size')).toBe('var(--app-font-size-table)')
    }
    const segmented = 'html[data-layout-preset] .el-segmented:not(.el-segmented--vertical)'
    expect(declaration('styles/global.css', segmented, 'min-height')).toBe('var(--app-choice-control-height)')
    expect(declaration('styles/global.css', 'html[data-layout-preset] .app-choice-button-card .el-radio-button__inner', '--app-choice-control-height')).toBe('auto')
    expect(declaration('styles/global.css', 'html[data-layout-preset] .app-choice-button-card .el-radio-button__inner', '--app-choice-justify')).toBe('start')
    expect(readFileSync(resolve('src/components/AppFilterSelect.vue'), 'utf8')).toContain('single-line')
    expect(declaration('components/AppFilterSelect.vue', '.app-filter-select__control :deep(.el-select__wrapper)', 'height')).toBeUndefined()
  })
})
