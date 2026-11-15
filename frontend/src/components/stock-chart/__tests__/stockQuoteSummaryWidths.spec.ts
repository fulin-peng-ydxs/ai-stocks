// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import StockQuoteSummary from '../StockQuoteSummary.vue'
import { stockQuoteSummaryHtml, stockQuoteSummaryWidths } from '../stockQuoteSummary'
import { buildKlineBarQuoteSummary } from '../chartUtils'
import { klineQuoteWindowWidths, stockQuoteWindow } from '../workspaceOptions'
import type { Bar } from '@/api/stocks'

function bar(close: number): Bar {
  return {
    date: '2026-10-09', open: close, high: close, low: close, close, pre_close: close,
    volume: 100_000, amount: 1_000_000, turnover_rate: 1,
  }
}
const palette = { text: '#111', label: '#666', up: '#f00', down: '#0a0', border: '#ddd' }

describe('可视窗口行情摘要容量', () => {
  it('排除窗口外历史，保留最新 K 线基线，窗口扩大后增宽、缩小后收窄', () => {
    const rows = [bar(123456), bar(9), bar(10), bar(11)].map((bar) => ({ bar }))
    const narrow = stockQuoteWindow(rows, 50, 100)
    expect(narrow.bars.map((bar) => bar.close)).toEqual([9, 10, 11])
    expect(klineQuoteWindowWidths(narrow).hero.value).toBe('calc(6ch + 0em)')
    const broad = klineQuoteWindowWidths(stockQuoteWindow(rows, 0, 100))
    expect(broad.hero.value).toBe('calc(11ch + 0em)')
    expect(klineQuoteWindowWidths(stockQuoteWindow(rows, 50, 100)))
      .toEqual(klineQuoteWindowWidths(narrow))
    const latestOutsideWindow = stockQuoteWindow([
      { bar: bar(9) }, { bar: bar(123456) },
    ], 0, 0)
    expect(klineQuoteWindowWidths(latestOutsideWindow).hero.value).toBe(broad.hero.value)
    expect(stockQuoteWindow([], 0, 100)).toEqual({ latestBar: null, bars: [], supplements: [] })
  })

  it('单位、符号、空值和测算辅助行共同预留，Vue 与浮层在短长值切换时复用容量', async () => {
    const short = buildKlineBarQuoteSummary(bar(9), {
      showChangeDetail: true,
      supplement: { label: '区间涨跌', value: '+1.00%', details: [{ label: '交易日', value: '1个交易日' }] },
    })
    const long = buildKlineBarQuoteSummary({ ...bar(125.6), amount: null }, {
      showChangeDetail: true,
      supplement: { label: '区间涨跌', value: '-125.00%', details: [{ label: '交易日', value: '123个交易日' }] },
    })
    const widths = stockQuoteSummaryWidths([short, long])
    expect(widths.hero.value).toBe('calc(7ch + 0em)')
    expect(widths.supplement?.value).toBe('calc(9ch + 0em)')
    expect(widths.supplement?.details[0]).toBe('calc(4ch + 4em)')
    expect(widths.columns[1].value).toContain('1em')
    const wrapper = mount(StockQuoteSummary, { props: { summary: short, widths } })
    const styles = () => wrapper.findAll('dd, dt, .stock-quote-summary__supplement-details span')
      .map((element) => element.attributes('style'))
    const before = styles()
    await wrapper.setProps({ summary: long })
    expect(styles()).toEqual(before)
    const htmlStyles = (summary: typeof short) => {
      const container = document.createElement('div')
      container.innerHTML = stockQuoteSummaryHtml(summary, palette, widths)
      return [...container.querySelectorAll<HTMLElement>('[style]')]
        .filter((element) => element.style.width)
        .map((element) => element.style.width)
    }
    expect(htmlStyles(short)).toEqual(htmlStyles(long))
    expect(htmlStyles(short)).toContain(widths.hero.value)
    wrapper.unmount()
  })

  it('数值只预留一个字符，不叠加其他字段的中文单位宽度', () => {
    const summary = buildKlineBarQuoteSummary(bar(10))
    summary.metrics = [
      { label: '振幅', value: '100.00%' },
      { label: '成交量', value: '1.00万手' },
      { label: '成交额', value: '—' },
    ]
    const widths = stockQuoteSummaryWidths([summary])
    expect(widths.columns[0].value)
      .toBe('max(calc(8ch + 0em), calc(5ch + 2em), calc(1ch + 1em))')
    expect(widths.columns[0].value).not.toContain('8ch + 2em')
  })

  it('HTML 和常驻摘要共同保留主题传入的序列身份色', () => {
    const summary = buildKlineBarQuoteSummary(bar(10))
    summary.metrics = [{ label: '均价', value: '10.00', color: '#e28a35' }]
    const wrapper = mount(StockQuoteSummary, { props: { summary } })
    expect(wrapper.get('.stock-quote-summary__metric dd').attributes('style'))
      .toContain('color: rgb(226, 138, 53)')
    expect(stockQuoteSummaryHtml(summary, palette)).toContain('color:#e28a35')
    wrapper.unmount()
  })

  it('截止测算独立底行，完整保留日期、收益和交易日且不额外增加表格列', () => {
    const summary = buildKlineBarQuoteSummary(bar(10), {
      showTime: true,
      supplement: { label: '截止 2026-10-20', value: '+12.34%', details: [{ label: '交易日', value: '123个交易日' }] },
    })
    const container = document.createElement('div')
    container.innerHTML = stockQuoteSummaryHtml(summary, palette, stockQuoteSummaryWidths([summary]))
    expect(container.querySelectorAll('tbody tr')).toHaveLength(4)
    expect(container.querySelectorAll('tbody tr:first-child > *')).toHaveLength(5)
    expect(container.querySelector('thead td')?.getAttribute('colspan')).toBe('4')
    expect(container.querySelector('table')?.textContent).not.toContain('截止')
    expect(container.querySelector('table + div')?.textContent)
      .toBe('截止 2026-10-20+12.34%123个交易日')
  })

  it('字段说明复用 HelpHint 图标，支持键盘触达且说明正文不改变容量', () => {
    const summary = buildKlineBarQuoteSummary(bar(10))
    summary.metrics = [
      { label: '总股本', value: '10.00亿股', hint: '最新采集值，不随 K 线日期变化。' },
      { label: '开盘', value: '10.00' },
    ]
    const widths = stockQuoteSummaryWidths([summary])
    expect(widths).toEqual(stockQuoteSummaryWidths([
      { ...summary, metrics: summary.metrics.map(({ hint: _hint, ...metric }) => metric) },
    ]))
    const wrapper = mount(StockQuoteSummary, {
      props: { summary, widths },
      global: {
        stubs: {
          ElTooltip: {
            props: ['content', 'trigger', 'disabled', 'popperClass'],
            template: '<div class="tooltip" :data-content="content" :data-trigger="trigger.join(\'|\')" :data-disabled="disabled" :data-popper-class="popperClass"><slot /></div>',
          },
        },
      },
    })
    const fields = wrapper.findAll('.stock-quote-summary__metric')
    expect(fields[0].get('dt > span').text()).toBe('总股本')
    expect(fields[0].get('dd').text()).toBe('10.00亿股')
    expect(fields[0].get('.help-hint').attributes('tabindex')).toBe('0')
    expect(fields[0].get('.help-hint').attributes('role')).toBe('button')
    expect(fields[0].get('.help-hint').text()).toBe('?')
    expect(fields[1].find('.help-hint').exists()).toBe(false)
    expect(fields[1].attributes('tabindex')).toBeUndefined()
    const hints = wrapper.findAll('.tooltip')
    expect(hints).toHaveLength(1)
    expect(hints[0].attributes()).toMatchObject({
      'data-content': summary.metrics[0].hint,
      'data-trigger': 'hover|focus',
      'data-disabled': 'false',
      'data-popper-class': 'app-wrapping-popper app-hover-info--tooltip help-hint-popper',
    })
    wrapper.unmount()
  })
})
