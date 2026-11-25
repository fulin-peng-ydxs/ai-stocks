// @vitest-environment jsdom
import { defineComponent, nextTick, provide, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import ChartOperationGroup from '@/components/ChartOperationGroup.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import StockChartOperationsDrawer from '../StockChartOperationsDrawer.vue'
import StockChartWorkspace from '../StockChartWorkspace.vue'
import { PAGE_OVERLAY_TARGET } from '@/layout/pageOverlay'

describe('StockChartOperationsDrawer', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('把抽屉限制在图表工作区并保留完整操作组边界', async () => {
    const Host = defineComponent({
      components: { ChartOperationGroup, PageSegmented, StockChartOperationsDrawer },
      setup() {
        const target = ref<HTMLElement | null>(null)
        const open = ref(true)
        provide(PAGE_OVERLAY_TARGET, target)
        return { target, open }
      },
      template: `
        <section ref="target" class="chart-host">
          <StockChartOperationsDrawer v-model="open" drawer-id="test-chart-operations">
            <ChartOperationGroup label="涨跌测算">
              <PageSegmented
                model-value="latest"
                :options="[{ label: '截止', value: 'latest' }, { label: '区间', value: 'range' }]"
              />
            </ChartOperationGroup>
          </StockChartOperationsDrawer>
        </section>
      `,
    })

    const wrapper = mount(Host, {
      attachTo: document.body,
      global: { plugins: [ElementPlus] },
    })
    await nextTick()
    await nextTick()

    const host = wrapper.get('.chart-host').element
    const overlay = document.querySelector('.el-overlay.page-drawer-modal--surface')
    expect(overlay).not.toBeNull()
    expect(overlay?.classList.contains('page-drawer-modal--title-compact')).toBe(true)
    expect(host.contains(overlay)).toBe(true)
    expect(document.querySelector('.stock-chart-operations-drawer')?.textContent)
      .toContain('涨跌测算截止区间')
    expect(document.querySelector('.page-drawer-surface')).not.toBeNull()
    const group = document.querySelector('.chart-operation-group')
    expect(group?.getAttribute('role')).toBe('group')
    expect(group?.getAttribute('aria-label')).toBe('涨跌测算')
    expect(group?.classList.contains('page-setting-item')).toBe(true)
    expect(group?.querySelector('.psi-control .page-segmented--fill')).not.toBeNull()
    expect(document.querySelector('.stock-chart-operations-drawer .sg')).toBeNull()
    expect(document.querySelector('.page-segmented--primary')).toBeNull()
    expect((document.querySelector('.el-drawer') as HTMLElement)?.style.width).toBe('320px')

    wrapper.unmount()
  })

  it('画布最小高度超出宿主时，把抽屉挂到已定位的可见裁切区', async () => {
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
    const wrapper = mount(defineComponent({
      components: { StockChartWorkspace },
      template: `<section class="chart-clip" style="position:relative;overflow:hidden;height:180px">
        <StockChartWorkspace :bars="[]" :range-days="120" />
      </section>`,
    }), {
      attachTo: document.body,
      global: { plugins: [ElementPlus], directives: { loading: {} } },
    })
    try {
      await nextTick()
      await nextTick()
      await wrapper.get('[data-testid="stock-chart-toggle-operations"]').trigger('click')
      await nextTick()
      const overlay = document.querySelector('.el-overlay.page-drawer-modal--surface')
      expect(overlay).not.toBeNull()
      expect(wrapper.get('.chart-clip').element.contains(overlay)).toBe(true)
      expect(wrapper.get('.stock-chart-workspace').element.contains(overlay)).toBe(false)
    } finally {
      wrapper.unmount()
      vi.unstubAllGlobals()
    }
  })
})
