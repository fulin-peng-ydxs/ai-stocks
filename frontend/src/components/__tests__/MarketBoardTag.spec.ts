// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { compileStyle, parse } from '@vue/compiler-sfc'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import MarketBoardTag from '../MarketBoardTag.vue'
import { formatMarketPercent } from '@/utils/marketValue'

describe('MarketBoardTag 展示变体', () => {
  it('夜间配方只作用于板块组件，不因 scoped 编译误改根背景', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/components/MarketBoardTag.vue'), 'utf8')
    const style = parse(source).descriptor.styles[0]!
    const compiled = compileStyle({ filename: 'MarketBoardTag.vue', source: style.content, id: 'data-v-board-test', scoped: true })
    expect(compiled.errors).toEqual([])
    expect(compiled.code).toContain('html.dark .market-board-tag[data-v-board-test]')
    expect(compiled.code).toContain('var(--board-direction) 8%, var(--el-fill-color-light)')
    expect(compiled.code).not.toMatch(/html\.dark\s*\{/)
  })

  it('详情默认保留名称、涨跌幅和走势相关标识', () => {
    const wrapper = mount(MarketBoardTag, {
      props: { name: '半导体', pctChg: 2.35, related: true },
    })
    expect(wrapper.get('.market-board-tag__name').text()).toBe('半导体')
    expect(wrapper.get('.market-board-tag__pct').text()).toBe('+2.35%')
    expect(wrapper.get('.market-board-tag__badge').text()).toBe('走势最相关')
    expect(wrapper.classes()).toContain('is-up')
    expect(wrapper.classes()).not.toContain('market-board-tag--compact')
  })

  it.each([2.35, -1.28, 0, null])('表格变体同行显示名称与涨跌幅，不增加角标（%s）', (pctChg) => {
    const wrapper = mount(MarketBoardTag, {
      props: { name: '共封装光学(CPO)', pctChg, related: true, variant: 'tag' },
    })
    expect(wrapper.get('.market-board-tag__name').text()).toBe('共封装光学(CPO)')
    expect(wrapper.get('.market-board-tag__pct').text()).toBe(formatMarketPercent(pctChg))
    expect(wrapper.classes()).toContain('market-board-tag--compact')
    expect(wrapper.find('.market-board-tag__badge').exists()).toBe(false)
  })
})
