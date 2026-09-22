// @vitest-environment jsdom
import { defineComponent, nextTick, provide, ref } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import ChartOperationGroup from '@/components/ChartOperationGroup.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import StockChartOperationsDrawer from '../StockChartOperationsDrawer.vue'
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
    expect(document.querySelector('.chart-operation-group.sg-l1')).not.toBeNull()
    expect(document.querySelector('.page-segmented--primary')).toBeNull()
    expect((document.querySelector('.el-drawer') as HTMLElement)?.style.width).toBe('320px')

    wrapper.unmount()
  })
})
