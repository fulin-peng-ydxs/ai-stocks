// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import RankedStockResultTable from '@/components/ranked-stock/RankedStockResultTable.vue'
import { rankedStockColumns } from '@/components/ranked-stock/types'

describe('RankedStockResultTable', () => {
  it.each([true, false])('名称入口与行点击等价（对比图标=%s）', async (analysisPins) => {
    const row = { code: '000001.SZ', name: '示例', rank: 1, total_score: 80, grade: 'A', sub_scores: {}, groups: [] }
    const wrapper = mount(RankedStockResultTable, {
      props: { rows: [row] as any, columns: rankedStockColumns(['name']), analysisPins },
      global: {
        plugins: [ElementPlus],
        stubs: {
          AppDataTable: { template: '<div><slot /></div>' },
          AppTableColumn: { setup: () => ({ row }), template: '<div><slot :row="row" /></div>' },
        },
      },
    })
    const button = wrapper.findAll('button').find(button => button.text() === '示例')!
    await button.trigger('click')
    expect(wrapper.emitted('rowClick')).toEqual([[row]])
    expect(wrapper.emitted('toggleAnalysis')).toBeUndefined()
    wrapper.unmount()
  })

  it('隐藏名称列仍保留同一行操作入口', () => {
    const wrapper = mount(RankedStockResultTable, {
      props: { rows: [], columns: rankedStockColumns(['code']) },
      global: { stubs: {
        AppDataTable: { template: '<div><slot /></div>' },
        AppTableColumn: { props: ['label'], template: '<div :data-label="label" />' },
      } },
    })
    expect(wrapper.find('[data-label="操作"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('把通用分页配置和事件透传给统一表格', async () => {
    const wrapper = mount(RankedStockResultTable, {
      props: {
        rows: [],
        columns: rankedStockColumns(['rank', 'code']),
        pagination: { currentPage: 2, pageSize: 50, total: 123, pageSizes: [20, 50, 100] },
      },
      global: {
        stubs: {
          AppDataTable: {
            name: 'AppDataTable',
            props: ['pagination'],
            emits: ['page-change', 'size-change'],
            template: '<div data-testid="table" @click="$emit(\'page-change\', 3)"><slot /></div>',
          },
          AppTableColumn: true,
        },
      },
    })

    expect(wrapper.findComponent({ name: 'AppDataTable' }).props('pagination')).toEqual({
      currentPage: 2, pageSize: 50, total: 123, pageSizes: [20, 50, 100],
    })
    await wrapper.get('[data-testid="table"]').trigger('click')
    expect(wrapper.emitted('pageChange')).toEqual([[3]])
  })

  it('统一展示全市场排名，以显式标签表达 ST 与未参与评分状态', () => {
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
            props: ['label', 'role', 'leadingControls'],
            template: `<section class="column" :data-label="label" :data-role="role" :data-leading-controls="leadingControls"><span>{{ label }}</span><slot :row="{
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
    expect(wrapper.get('.stock-status-tag').text()).toBe('ST')
    expect(wrapper.get('[data-label="全市场排名"]').attributes('data-role')).toBe('rank')
    expect(wrapper.get('[data-label="综合分"]').attributes('data-role')).toBe('number')
    expect(wrapper.get('[data-label="评级"]').attributes('data-role')).toBe('status')
    expect(wrapper.get('[data-label="名称"]').attributes('data-leading-controls')).toBe('0')
  })

  it('走势工作台模式同样显示显式 ST 标签', () => {
    const wrapper = mount(RankedStockResultTable, {
      props: {
        rows: [{
          rank: 8, code: '600001.SH', name: '风险样例', board: '主板',
          total_score: 76, grade: '观察', sub_scores: {}, is_st: true,
          score_status: 'ranked', related_boards: null, groups: [],
        }],
        columns: rankedStockColumns(['rank', 'name', 'score']),
        nameLeadingControls: 1,
      },
      global: {
        plugins: [ElementPlus],
        stubs: {
          AppDataTable: {
            props: ['data'],
            template: '<div><slot /></div>',
          },
          AppTableColumn: {
            props: ['label', 'role', 'leadingControls'],
            template: `<section class="column" :data-label="label" :data-role="role" :data-leading-controls="leadingControls"><span>{{ label }}</span><slot :row="{
              rank: 8, code: '600001.SH', name: '风险样例', board: '主板',
              total_score: 76, grade: '观察', sub_scores: {}, is_st: true,
              score_status: 'ranked', related_boards: null, groups: [],
            }" /></section>`,
          },
        },
      },
    })

    expect(wrapper.get('.stock-analysis-name-cell__name').text()).toBe('风险样例')
    expect(wrapper.get('.stock-status-tag').text()).toBe('ST')
    expect(wrapper.get('[data-label="名称"]').attributes('data-role')).toBe('entity')
    expect(wrapper.get('[data-label="名称"]').attributes('data-leading-controls')).toBe('2')
  })
})
