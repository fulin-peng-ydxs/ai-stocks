// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import SectorAnalysisDefaultFields from '@/components/SectorAnalysisDefaultFields.vue'

describe('SectorAnalysisDefaultFields', () => {
  it('指标列表不可为空，移除默认指标时同步回退到首个可见指标', async () => {
    const wrapper = mount(SectorAnalysisDefaultFields, {
      props: {
        defaultChartMode: 'compare',
        benchmarkCode: '000905.SH',
        showAnalysisPanel: true,
        compareMetrics: ['cum', 'inflow'],
        defaultCompareMetric: 'inflow',
        compareWindow: 120,
      },
      global: { plugins: [ElementPlus] },
    })

    await wrapper.setProps({ compareMetrics: ['cum'] })
    expect(wrapper.emitted('update:defaultCompareMetric')?.at(-1)).toEqual(['cum'])

    await wrapper.setProps({ compareMetrics: [], defaultCompareMetric: 'cum' })
    expect(wrapper.emitted('update:compareMetrics')?.at(-1)).toEqual([['cum']])
  })
})
