// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { defineComponent, h } from 'vue'
import { compileStyle, parse } from '@vue/compiler-sfc'
import ElementPlus from 'element-plus'
import AppDataTable from '@/components/AppDataTable.vue'
import appDataTableSource from '@/components/AppDataTable.vue?raw'
import { LONG_DOCUMENT_TABLE_MAX_HEIGHT } from '@/components/table/tableSizing'

const ElTableStub = defineComponent({
  name: 'ElTable',
  props: ['data', 'border', 'fit', 'height', 'maxHeight', 'scrollbarAlwaysOn'],
  emits: ['sort-change', 'row-click'],
  setup(props, { slots, emit }) {
    return () => h('div', {
      class: 'el-table',
      'data-border': String(props.border),
      'data-fit': String(props.fit),
      'data-scrollbar-always-on': String(props.scrollbarAlwaysOn),
    }, [
      h('table', { class: 'el-table__header' }),
      h('table', { class: 'el-table__body' }),
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
  it('普通列与左右固定列即时切换行底色，不覆盖单元格内部控件的过渡', () => {
    const vendorStyle = document.createElement('style')
    vendorStyle.textContent = readFileSync('node_modules/element-plus/theme-chalk/el-table.css', 'utf8')
    const fixture = document.createElement('div')
    fixture.setAttribute('data-v-table-test', '')
    fixture.innerHTML = `<div class="el-table el-table--enable-row-transition">
      <table class="el-table__body"><tbody><tr class="el-table__row">
        <td class="el-table__cell el-table-fixed-column--left">左侧</td>
        <td class="el-table__cell">正文</td>
        <td class="el-table__cell el-table-fixed-column--right"><button style="transition: opacity .1s">更多</button></td>
      </tr></tbody></table></div>`
    const sharedStyle = document.createElement('style')
    const styles = parse(appDataTableSource).descriptor.styles
    sharedStyle.textContent = styles.map(style => compileStyle({
      source: style.content, filename: 'AppDataTable.vue',
      id: 'data-v-table-test', scoped: style.scoped,
    }).code).join('\n')
    document.head.append(vendorStyle)
    document.body.append(fixture)
    try {
      const cells = [...fixture.querySelectorAll('td')]
      // 库默认确实存在渐变；回归必须能检测到未覆盖的旧行为。
      expect(cells.map(cell => getComputedStyle(cell).transition)).toEqual(Array(3).fill('background-color .25s 1ms'))
      document.head.append(sharedStyle)
      fixture.className = 'app-data-table'
      for (const state of ['el-table__row', 'el-table__row hover-row', 'el-table__row current-row']) {
        fixture.querySelector('tr')!.className = state
        expect(cells.map(cell => getComputedStyle(cell).transition)).toEqual(['none', 'none', 'none'])
      }
      expect(getComputedStyle(fixture.querySelector('button')!).transition).toBe('opacity .1s')
    } finally {
      fixture.remove()
      vendorStyle.remove()
      sharedStyle.remove()
    }
  })

  it('嵌入表默认限高，显式高度、上限及完整展开可动态覆盖且不影响主表', async () => {
    const wrapper = mount(AppDataTable, {
      props: { data: [], embedded: true },
      global: { directives: { loading: {} }, stubs: { ElTable: ElTableStub } },
    })
    const table = () => wrapper.findComponent(ElTableStub)
    expect(table().props('height')).toBeUndefined()
    expect(table().props('maxHeight')).toBe(LONG_DOCUMENT_TABLE_MAX_HEIGHT)
    await wrapper.setProps({ height: 640 })
    expect(table().props('height')).toBe(640)
    expect(table().props('maxHeight')).toBeUndefined()
    await wrapper.setProps({ maxHeight: '220' })
    expect(table().props('maxHeight')).toBe('220')
    await wrapper.setProps({ height: undefined, maxHeight: 480 })
    expect(table().props('maxHeight')).toBe(480)
    await wrapper.setProps({ maxHeight: null })
    expect(table().props('maxHeight')).toBeUndefined()
    await wrapper.setProps({ maxHeight: undefined })
    expect(table().props('maxHeight')).toBe(LONG_DOCUMENT_TABLE_MAX_HEIGHT)
    await wrapper.setProps({ embedded: false })
    expect(table().props('height')).toBe('100%')
    expect(table().props('maxHeight')).toBeUndefined()
    wrapper.unmount()
  })
  it('无旧数据加载时显示骨架，有旧数据刷新时保留表格遮罩', async () => {
    const wrapper = mount(AppDataTable, {
      props: {
        data: [],
        loading: true,
        loadingText: '正在加载审计记录…',
        height: 460,
        pagination: { currentPage: 1, pageSize: 50, total: 0 },
      },
      global: {
        plugins: [ElementPlus],
        stubs: {
          ElTable: ElTableStub,
          AppPagination: AppPaginationStub,
        },
      },
    })

    expect(wrapper.find('[data-testid="app-data-table-initial-loading"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('正在加载审计记录…')
    expect(wrapper.find('.el-table').exists()).toBe(false)
    expect(wrapper.find('.app-pagination-stub').exists()).toBe(false)
    expect(wrapper.find('[data-testid="app-data-table-initial-loading"]').attributes('style')).toContain('height: 460px')
    expect(wrapper.attributes('aria-busy')).toBe('true')

    await wrapper.setProps({ data: [{ code: '000001' }] })
    expect(wrapper.find('[data-testid="app-data-table-initial-loading"]').exists()).toBe(false)
    expect(wrapper.find('.el-table').exists()).toBe(true)
    expect(wrapper.find('.el-table').attributes('aria-busy')).toBe('true')
    expect(wrapper.find('.app-pagination-stub').exists()).toBe(true)
  })

  it('渲染真实表格外壳并透传表格与分页事件', async () => {
    const wrapper = mount(AppDataTable, {
      props: {
        data: [{ code: '000001' }],
        kind: 'wide-table',
        clickable: true,
        ariaLabel: '测试数据',
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
    await wrapper.vm.$nextTick()

    expect(wrapper.classes()).toContain('app-data-table--wide-table')
    expect(wrapper.classes()).toContain('app-data-table--fill')
    expect(wrapper.classes()).toContain('app-data-table--clickable')
    expect(wrapper.find('.el-table').attributes('data-border')).toBe('false')
    expect(wrapper.find('.el-table').attributes('data-fit')).toBe('true')
    expect(wrapper.find('.el-table').attributes('data-scrollbar-always-on')).toBe('true')
    expect(wrapper.find('.el-table').attributes('aria-busy')).toBe('false')
    expect(wrapper.find('.el-table__header').attributes('aria-label')).toBe('测试数据表头')
    expect(wrapper.find('.el-table__body').attributes('aria-label')).toBe('测试数据')
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

  it('嵌入式表格不强制占满父容器', () => {
    const wrapper = mount(AppDataTable, {
      props: {
        data: [],
        embedded: true,
      },
      global: {
        directives: { loading: {} },
        stubs: {
          ElTable: ElTableStub,
          AppPagination: AppPaginationStub,
        },
      },
    })

    expect(wrapper.classes()).toContain('app-data-table--embedded')
    expect(wrapper.classes()).not.toContain('app-data-table--fill')
    // 内部轨道交由全站策略统一显隐，嵌入模式不再有独立显隐分支。
    expect(wrapper.find('.el-table').attributes('data-scrollbar-always-on')).toBe('true')
  })

  it('嵌入式表格保持内容自然高度，不被父级纵向压缩', () => {
    const embeddedRule = appDataTableSource.match(/\.app-data-table--embedded \{([^}]*)\}/)?.[1] ?? ''
    expect(embeddedRule).toContain('height: auto')
    expect(embeddedRule).toContain('flex: 0 0 auto')
  })
})
