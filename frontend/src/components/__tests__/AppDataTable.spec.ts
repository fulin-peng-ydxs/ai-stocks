// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { defineComponent, h } from 'vue'
import AppDataTable from '@/components/AppDataTable.vue'

const ElTableStub = defineComponent({
  name: 'ElTable',
  props: ['data'],
  emits: ['sort-change', 'row-click'],
  setup(_props, { slots, emit }) {
    return () => h('div', { class: 'el-table' }, [
      h('button', { class: 'sort-btn', onClick: () => emit('sort-change', { prop: 'code', order: 'ascending' }) }, 'sort'),
      h('button', { class: 'row-btn', onClick: () => emit('row-click', { code: '000001' }, null, new Event('click')) }, 'row'),
      slots.default?.(),
      slots.empty?.(),
    ])
  },
})

const AppPaginationStub = defineComponent({
  name: 'AppPagination',
  emits: ['current-change', 'size-change'],
  setup(_props, { emit }) {
    return () => h('div', { class: 'app-pagination-stub' }, [
      h('button', { class: 'page-btn', onClick: () => emit('current-change', 2) }, 'page'),
      h('button', { class: 'size-btn', onClick: () => emit('size-change', 100) }, 'size'),
    ])
  },
})

describe('AppDataTable', () => {
  it('渲染真实表格外壳并透传表格与分页事件', async () => {
    const wrapper = mount(AppDataTable, {
      props: {
        data: [{ code: '000001' }],
        kind: 'wide-table',
        clickable: true,
        pagination: { currentPage: 1, pageSize: 50, total: 120 },
      },
      slots: {
        default: '<span class="column-slot">代码列</span>',
        empty: '<span class="empty-slot">暂无数据</span>',
      },
      global: {
        directives: {
          loading: {},
        },
        stubs: {
          ElTable: ElTableStub,
          AppPagination: AppPaginationStub,
        },
      },
    })

    expect(wrapper.classes()).toContain('app-data-table--wide-table')
    expect(wrapper.classes()).toContain('app-data-table--clickable')
    expect(wrapper.find('.column-slot').text()).toBe('代码列')
    expect(wrapper.find('.empty-slot').text()).toBe('暂无数据')

    await wrapper.find('.sort-btn').trigger('click')
    await wrapper.find('.row-btn').trigger('click')
    await wrapper.find('.page-btn').trigger('click')
    await wrapper.find('.size-btn').trigger('click')

    expect(wrapper.emitted('sort-change')?.[0][0]).toMatchObject({ prop: 'code', order: 'ascending' })
    expect(wrapper.emitted('row-click')?.[0][0]).toMatchObject({ code: '000001' })
    expect(wrapper.emitted('page-change')?.[0]).toEqual([2])
    expect(wrapper.emitted('size-change')?.[0]).toEqual([100])
  })
})
