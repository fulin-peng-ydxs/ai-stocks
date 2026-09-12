// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import MarketDetailHero from '@/components/MarketDetailHero.vue'
import StockBoardMembershipPanel from '@/components/StockBoardMembershipPanel.vue'
import StockQuoteSummary from '@/components/stock-chart/StockQuoteSummary.vue'
import type { StockBoardMembership } from '@/api/stocks'

const ElCardStub = {
  template: '<section><header><slot name="header" /></header><slot /></section>',
}
const ElTagStub = {
  name: 'ElTag',
  props: ['size', 'effect'],
  template: '<span class="el-tag"><slot /></span>',
}
const RouterLinkStub = {
  name: 'RouterLink',
  props: ['to'],
  template: '<a><slot /></a>',
}

describe('MarketDetailHero', () => {
  it('以同一结构承载身份、摘要、元信息与上下文操作', () => {
    const wrapper = mount(MarketDetailHero, {
      props: { title: '浦发银行', code: '600000.SH' },
      slots: {
        badges: '<span>主板</span>',
        summary: '<div>行情摘要</div>',
        meta: '<span>行情 2026-09-10</span>',
        footer: '<button>下一只</button>',
      },
    })

    expect(wrapper.text()).toContain('浦发银行')
    expect(wrapper.text()).toContain('主板')
    expect(wrapper.text()).toContain('行情摘要')
    expect(wrapper.text()).toContain('下一只')
    expect(wrapper.find('.market-detail-hero__eyebrow').exists()).toBe(false)
  })

  it('只在消费页显式指定时把摘要靠左排列', () => {
    const normal = mount(MarketDetailHero, {
      props: { title: '银行', code: '881001' },
      slots: { summary: '<div>摘要</div>' },
    })
    const aligned = mount(MarketDetailHero, {
      props: { title: '浦发银行', code: '600000.SH', asideAlign: 'start' },
      slots: { summary: '<div>摘要</div>' },
    })

    expect(normal.classes()).toContain('market-detail-hero--aside-end')
    expect(aligned.classes()).toContain('market-detail-hero--aside-start')
  })
})

describe('StockQuoteSummary', () => {
  it('按每列四行分组并展示主值涨跌辅助行', () => {
    const wrapper = mount(StockQuoteSummary, {
      props: {
        summary: {
          hero: {
            label: '',
            value: '10.20',
            tone: 'up',
            details: [{ label: '涨幅', value: '+2.00%', tone: 'up' }],
          },
          rowsPerColumn: 4,
          metrics: Array.from({ length: 11 }, (_, index) => ({
            label: `字段${index + 1}`,
            value: String(index + 1),
            tone: index === 0 ? 'down' as const : undefined,
          })),
        },
      },
    })

    expect(wrapper.findAll('.stock-quote-summary__column')).toHaveLength(3)
    expect(wrapper.findAll('.stock-quote-summary__column')[0]!.findAll('div')).toHaveLength(4)
    expect(wrapper.get('.stock-quote-summary__hero-details').text()).toBe('+2.00%')
    expect(wrapper.find('.stock-quote-summary__metric dd').classes()).toContain('is-down')
  })

  it('只在显式配置时放宽列间距', () => {
    const summary = {
      hero: { label: '', value: '10.20', tone: 'up' as const },
      rowsPerColumn: 4,
      metrics: [{ label: '开盘', value: '10.00' }],
    }
    const standard = mount(StockQuoteSummary, { props: { summary } })
    const relaxed = mount(StockQuoteSummary, { props: { summary, columnGap: 'relaxed' } })

    expect(standard.classes()).toContain('stock-quote-summary--gap-standard')
    expect(standard.classes()).not.toContain('stock-quote-summary--gap-relaxed')
    expect(relaxed.classes()).toContain('stock-quote-summary--gap-relaxed')
  })
})

describe('StockBoardMembershipPanel', () => {
  const membership: StockBoardMembership = {
    code: '600000.SH',
    membership_scope: 'cumulative',
    membership_updated_at: '2026-09-10T18:00:00',
    trade_date: '2026-09-10',
    industries: [{ board_code: '881001', name: '银行', board_type: 'industry', pct_chg: 2 }],
    concepts: [{ board_code: '301001', name: '中特估', board_type: 'concept', pct_chg: -1.5 }],
    related_boards: {
      as_of_date: '2026-09-10',
      benchmark: { code: '000001.SH', name: '上证指数', fallback: false },
      industry: {
        board_code: '881001', name: '银行', score: 0.8, corr_20: 0.8, corr_60: 0.8,
        sample_20: 20, sample_60: 60, confidence: 'high',
      },
      concept: null,
    },
  }

  it('标题旁展示最相关行业，正文直接展示概念标签', () => {
    const wrapper = mount(StockBoardMembershipPanel, {
      props: { membership, canNavigate: false },
      global: {
        stubs: {
          ElCard: ElCardStub,
          ElTag: ElTagStub,
          AppStateBlock: true,
          RouterLink: RouterLinkStub,
        },
        directives: { loading: {} },
      },
    })

    expect(wrapper.text()).not.toContain('所属行业')
    expect(wrapper.text()).not.toContain('所属概念')
    expect(wrapper.text()).toContain('+2.00%')
    expect(wrapper.text()).toContain('-1.50%')
    const industry = wrapper.get('[data-testid="stock-board-related-industry"]')
    expect(industry.classes()).toContain('stock-board-membership__featured')
    expect(industry.get('.market-board-tag').classes()).toContain('is-related')
    expect(industry.getComponent(ElTagStub).props()).toMatchObject({
      size: 'default',
      effect: 'plain',
    })
    expect(wrapper.text()).toContain('最相关')
  })

  it('概念标签按内容自然换行而不增加分组标题', () => {
    const wrapper = mount(StockBoardMembershipPanel, {
      props: { membership },
      global: {
        stubs: {
          ElCard: ElCardStub,
          ElTag: ElTagStub,
          AppStateBlock: true,
          RouterLink: RouterLinkStub,
        },
        directives: { loading: {} },
      },
    })

    expect(wrapper.text()).not.toContain('所属行业')
    expect(wrapper.text()).not.toContain('所属概念')
    expect(wrapper.find('.stock-board-membership__grid').exists()).toBe(true)
  })

  it('有权限时复用板块详情地址并携带个股返回路径', () => {
    const wrapper = mount(StockBoardMembershipPanel, {
      props: { membership, canNavigate: true, returnPath: '/stocks/600000.SH' },
      global: {
        stubs: {
          ElCard: ElCardStub,
          ElTag: ElTagStub,
          AppStateBlock: true,
          RouterLink: RouterLinkStub,
        },
        directives: { loading: {} },
      },
    })

    const link = wrapper.findComponent(RouterLinkStub)
    expect(link.props('to')).toEqual({
      path: '/sectors/881001',
      query: { return_to: '/stocks/600000.SH' },
    })
  })
})
