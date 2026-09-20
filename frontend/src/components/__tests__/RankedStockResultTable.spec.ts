// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import RankedStockResultTable from '@/components/ranked-stock/RankedStockResultTable.vue'
import { rankedStockColumns } from '@/components/ranked-stock/types'

describe('RankedStockResultTable', () => {
  it('统一展示全市场排名，以名称警告色表达 ST 与未参与评分状态', () => {
    const wrapper = mount(RankedStockResultTable, {
      props: {
        rows: [
          {
            rank: null, code: '000001.SZ', name: '示例ST', board: '主板',
            total_score: null, grade: '', sub_scores: {}, is_st: true,
            score_status: 'excluded_st', related_boards: null, groups: [],
          },
        ],
        columns: rankedStockColumns(['rank', 'code', 'name', 'score', 'grade']),
        analysisPins: false,
      },
      global: {
        plugins: [ElementPlus],
        stubs: {
          AppDataTable: {
            props: ['data'],
            template: '<div><slot /></div>',
          },
          AppTableColumn: {
            props: ['label'],
            template: `<section><span>{{ label }}</span><slot :row="{
              rank: null, code: '000001.SZ', name: '示例ST', board: '主板',
              total_score: null, grade: '', sub_scores: {}, is_st: true,
              score_status: 'excluded_st', related_boards: null, groups: [],
            }" /></section>`,
          },
        },
      },
    })

    expect(wrapper.text()).toContain('全市场排名')
    expect(wrapper.text()).toContain('示例ST')
    expect(wrapper.text()).toContain('该方案未纳入 ST')
    expect(wrapper.get('.ranked-stock-name--st').text()).toBe('示例ST')
    expect(wrapper.findAll('.el-tag')).toHaveLength(0)
  })

  it('走势工作台模式同样把 ST 状态收进名称警告色', () => {
    const wrapper = mount(RankedStockResultTable, {
      props: {
        rows: [{
          rank: 8, code: '600001.SH', name: '风险样例', board: '主板',
          total_score: 76, grade: '观察', sub_scores: {}, is_st: true,
          score_status: 'ranked', related_boards: null, groups: [],
        }],
        columns: rankedStockColumns(['rank', 'name', 'score']),
      },
      global: {
        plugins: [ElementPlus],
        stubs: {
          AppDataTable: {
            props: ['data'],
            template: '<div><slot /></div>',
          },
          AppTableColumn: {
            props: ['label'],
            template: `<section><span>{{ label }}</span><slot :row="{
              rank: 8, code: '600001.SH', name: '风险样例', board: '主板',
              total_score: 76, grade: '观察', sub_scores: {}, is_st: true,
              score_status: 'ranked', related_boards: null, groups: [],
            }" /></section>`,
          },
        },
      },
    })

    expect(wrapper.get('.stock-analysis-name-cell__name.is-warning').text()).toBe('风险样例')
    expect(wrapper.findAll('.el-tag')).toHaveLength(0)
  })
})
