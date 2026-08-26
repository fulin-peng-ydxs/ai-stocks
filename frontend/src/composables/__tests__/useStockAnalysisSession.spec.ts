import { nextTick, reactive, ref } from 'vue'
import { describe, expect, it } from 'vitest'
import { useStockAnalysisSession } from '@/composables/useStockAnalysisSession'

describe('useStockAnalysisSession', () => {
  it('远端水合和抽屉修改会单向更新会话，主区修改不反写默认值', async () => {
    const settings = reactive({
      defaultChartMode: 'compare',
      showAnalysisPanel: true,
      compareRange: 60,
      benchmarkCode: '000905.SH',
      compareMetrics: ['cum', 'roll_30d', 'roll_60d'],
      defaultCompareMetric: 'cum',
    })
    const klineDefault = ref(120)
    const session = useStockAnalysisSession(settings, klineDefault)

    session.chartMode.value = 'kline'
    session.compareRange.value = 20
    session.analysisPanelVisible.value = false
    session.klineRange.value = 60
    session.benchmarkCode.value = '000300.SH'
    session.compareMetric.value = 'roll_60d'
    expect(settings).toEqual({
      defaultChartMode: 'compare',
      showAnalysisPanel: true,
      compareRange: 60,
      benchmarkCode: '000905.SH',
      compareMetrics: ['cum', 'roll_30d', 'roll_60d'],
      defaultCompareMetric: 'cum',
    })
    expect(klineDefault.value).toBe(120)

    settings.defaultChartMode = 'kline'
    settings.compareRange = 250
    settings.showAnalysisPanel = false
    settings.benchmarkCode = '000300.SH'
    settings.defaultCompareMetric = 'roll_30d'
    klineDefault.value = 250
    await nextTick()

    expect(session.chartMode.value).toBe('kline')
    expect(session.compareRange.value).toBe(250)
    expect(session.analysisPanelVisible.value).toBe(false)
    expect(session.klineRange.value).toBe(250)
    expect(session.benchmarkCode.value).toBe('000300.SH')
    expect(session.compareMetric.value).toBe('roll_30d')
    expect(session.visibleCompareMetrics.value).toEqual(['cum', 'roll_30d', 'roll_60d'])
  })

  it('非法持久化值回落到稳定默认值', () => {
    const settings = reactive({
      defaultChartMode: 'unknown',
      showAnalysisPanel: null,
      compareRange: 17,
      adjustMode: 'bogus',
    })
    const session = useStockAnalysisSession(settings, ref(120))

    expect(session.chartMode.value).toBe('compare')
    expect(session.compareRange.value).toBe(60)
    expect(session.analysisPanelVisible.value).toBe(true)
    expect(session.adjustMode.value).toBe('qfq')
  })

  it('新增市场指数可作为个股分析默认基准', () => {
    const settings = reactive({
      defaultChartMode: 'compare',
      showAnalysisPanel: true,
      compareRange: 60,
      benchmarkCode: '000688.SH',
    })
    const session = useStockAnalysisSession(settings, ref(120))

    expect(session.benchmarkCode.value).toBe('000688.SH')
  })

  it('复权口径随抽屉默认单向进入会话', async () => {
    const settings = reactive({
      defaultChartMode: 'kline',
      showAnalysisPanel: true,
      compareRange: 60,
      adjustMode: '',
    })
    const session = useStockAnalysisSession(settings, ref(120))

    expect(session.adjustMode.value).toBe('')
    settings.adjustMode = 'hfq'
    await nextTick()
    expect(session.adjustMode.value).toBe('hfq')
    expect(settings.adjustMode).toBe('hfq')
  })
})
