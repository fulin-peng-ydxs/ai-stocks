import { describe, expect, it } from 'vitest'
import { nextTick, reactive, ref } from 'vue'
import {
  createDefaultStockChartPreferences,
  normalizeStockChartPreferences,
} from '@/composables/useStockChartPreferences'
import { useStockChartComponentConfig } from '@/composables/useStockChartComponentConfig'
import { createDefaultStockAnalysisPreferences } from '@/composables/useStockAnalysisSession'

describe('useStockChartComponentConfig', () => {
  it('拖动比例只进入待采用样本，不提前覆盖抽屉配置基线', () => {
    const stored = ref(createDefaultStockChartPreferences())
    const config = useStockChartComponentConfig({
      componentValueOf: () => stored.value,
      setComponentKnob: (_slotId, _field, value) => {
        stored.value = normalizeStockChartPreferences(value)
      },
      hydrated: ref(true),
    })
    const measurement = {
      width: 1280,
      height: 720,
      minimumRatios: [0.2, 0.1, 0.1],
    }

    config.handleWorkspaceResize({
      ...measurement,
      ratios: [0.6, 0.2, 0.2],
    })
    config.handleRatioDraft([0.5, 0.3, 0.2])
    config.handleRatioCommit([0.5, 0.3, 0.2])
    config.handleWorkspaceResize({
      ...measurement,
      ratios: [0.5, 0.3, 0.2],
    })

    const configured = normalizeStockChartPreferences(
      config.componentRuntimeValueOf('chart', 'stockChartConfigured'),
    )
    const current = normalizeStockChartPreferences(
      config.componentRuntimeValueOf('chart', 'stockChart'),
    )
    expect(configured.heightRatios['kline|volume|macd']).toEqual([0.6, 0.2, 0.2])
    expect(current.heightRatios['kline|volume|macd']).toEqual([0.5, 0.3, 0.2])
  })

  it('工作区离开页面后清除当前比例样本，避免采用隐藏页面旧值', () => {
    const stored = ref(createDefaultStockChartPreferences())
    const config = useStockChartComponentConfig({
      componentValueOf: () => stored.value,
      setComponentKnob: (_slotId, _field, value) => {
        stored.value = normalizeStockChartPreferences(value)
      },
      hydrated: ref(true),
    })

    config.handleWorkspaceResize({
      width: 1280,
      height: 720,
      ratios: [0.5, 0.3, 0.2],
      minimumRatios: [0.2, 0.1, 0.1],
    })
    expect(config.componentRuntimeValueOf('chart', 'stockChartRatioSample')).toBeDefined()

    config.handleWorkspaceResize(undefined)

    expect(config.componentRuntimeValueOf('chart', 'stockChartRatioSample')).toBeUndefined()
    expect(normalizeStockChartPreferences(
      config.componentRuntimeValueOf('chart', 'stockChartConfigured'),
    ).heightRatios['kline|volume|macd']).toEqual([0.6, 0.2, 0.2])
  })

  it('把组件登记的测算默认值单向投影为当前页面会话值', async () => {
    const stored = reactive<Record<string, unknown>>({
      stockChart: createDefaultStockChartPreferences(),
      measurementOperationsExpanded: false,
      returnMeasurementMode: 'latest',
    })
    const config = useStockChartComponentConfig({
      componentValueOf: (_slotId, field) => stored[field],
      setComponentKnob: (_slotId, field, value) => { stored[field] = value },
      hydrated: ref(true),
    })

    stored.measurementOperationsExpanded = true
    stored.returnMeasurementMode = 'range'
    await nextTick()
    expect(config.measurementOperationsExpanded.value).toBe(true)
    expect(config.returnMeasurementMode.value).toBe('range')

    config.measurementOperationsExpanded.value = false
    config.returnMeasurementMode.value = 'latest'
    expect(stored.measurementOperationsExpanded).toBe(true)
    expect(stored.returnMeasurementMode).toBe('range')
  })

  it('通过组件配置读写联动走势工作台默认项', () => {
    const stored = reactive<Record<string, unknown>>({
      stockChart: createDefaultStockChartPreferences(),
      stockAnalysis: createDefaultStockAnalysisPreferences(),
    })
    const config = useStockChartComponentConfig({
      componentValueOf: (_slotId, field) => stored[field],
      setComponentKnob: (_slotId, field, value) => { stored[field] = value },
      hydrated: ref(true),
    })

    config.stockAnalysis.value = {
      ...config.stockAnalysis.value,
      defaultChartMode: 'kline',
      compareRange: 120,
    }

    expect(stored.stockAnalysis).toMatchObject({ defaultChartMode: 'kline', compareRange: 120 })
  })
})
