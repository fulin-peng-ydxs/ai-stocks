import { computed, nextTick, ref } from 'vue'
import { describe, expect, it } from 'vitest'
import {
  chartCompositionKey,
  createDefaultStockChartPreferences,
  normalizeHeightRatios,
  normalizeStockChartPreferences,
  setAuxiliaryChartType,
  useStockChartPreferences,
  visibleChartTypes,
  type AuxiliaryChartType,
  type StockChartPreferences,
} from '@/composables/useStockChartPreferences'

const TYPES: AuxiliaryChartType[] = ['volume', 'macd', 'hidden']

describe('useStockChartPreferences pure helpers', () => {
  it.each(TYPES.flatMap((slot2) => TYPES.map((slot3) => [slot2, slot3] as const)))(
    '归一化图表二=%s、图表三=%s 的全部组合',
    (slot2, slot3) => {
      const normalized = normalizeStockChartPreferences({ slot2, slot3 })
      const duplicated = slot2 !== 'hidden' && slot2 === slot3

      expect([normalized.slot2, normalized.slot3]).toEqual(
        duplicated ? ['volume', 'macd'] : [slot2, slot3],
      )
      expect(visibleChartTypes(normalized)[0]).toBe('kline')
    },
  )

  it('非法枚举只回退对应槽位，存量重复组合整体回默认', () => {
    expect(normalizeStockChartPreferences({
      slot2: 'broken',
      slot3: 'hidden',
    })).toMatchObject({ slot2: 'volume', slot3: 'hidden' })
    expect(normalizeStockChartPreferences({
      slot2: 'macd',
      slot3: 'macd',
    })).toMatchObject({ slot2: 'volume', slot3: 'macd' })
    expect(normalizeStockChartPreferences({
      slot2: 'broken',
      slot3: 'volume',
    })).toMatchObject({ slot2: 'macd', slot3: 'volume' })
    expect(normalizeStockChartPreferences({
      slot2: 'macd',
      slot3: 'broken',
    })).toMatchObject({ slot2: 'macd', slot3: 'volume' })
  })

  it('实时选择冲突类型时自动交换，原槽隐藏时另一槽随交换隐藏', () => {
    const defaults = createDefaultStockChartPreferences()
    expect(setAuxiliaryChartType(defaults, 'slot2', 'macd')).toMatchObject({
      slot2: 'macd',
      slot3: 'volume',
    })

    const hidden = setAuxiliaryChartType(defaults, 'slot2', 'hidden')
    expect(setAuxiliaryChartType(hidden, 'slot2', 'macd')).toMatchObject({
      slot2: 'macd',
      slot3: 'hidden',
    })
  })

  it('composition key 始终包含固定 K线并保留辅助图顺序', () => {
    expect(chartCompositionKey({ slot2: 'volume', slot3: 'macd' }))
      .toBe('kline|volume|macd')
    expect(chartCompositionKey({ slot2: 'macd', slot3: 'volume' }))
      .toBe('kline|macd|volume')
    expect(chartCompositionKey({ slot2: 'hidden', slot3: 'macd' }))
      .toBe('kline|macd')
    expect(chartCompositionKey({ slot2: 'hidden', slot3: 'hidden' }))
      .toBe('kline')
  })

  it.each([
    [-0.1, 0.6, 0.5],
    [0, 0.5, 0.5],
    [Number.NaN, 0.5, 0.5],
    [Number.POSITIVE_INFINITY, 0.5, 0.5],
    [Number.NEGATIVE_INFINITY, 0.5, 0.5],
    [0.5, 0.5],
    [0.5, 0.2, 0.2],
  ])('非法三图比例 %j 回退当前组合默认值', (...ratios) => {
    expect(normalizeHeightRatios(ratios, 'kline|volume|macd')).toEqual([0.6, 0.2, 0.2])
  })

  it('单个组合非法时只回退该组合，保留其他合法组合高度', () => {
    const normalized = normalizeStockChartPreferences({
      slot2: 'volume',
      slot3: 'macd',
      heightRatios: {
        'kline|volume|macd': [0.5, 0.2, 0.2],
        'kline|macd|volume': [0.5, 0.3, 0.2],
        'kline|volume': [0.7, 0.3],
      },
    })

    expect(normalized.heightRatios['kline|volume|macd']).toEqual([0.6, 0.2, 0.2])
    expect(normalized.heightRatios['kline|macd|volume']).toEqual([0.5, 0.3, 0.2])
    expect(normalized.heightRatios['kline|volume']).toEqual([0.7, 0.3])
  })

  it('隐藏和重显不删除原有序组合高度', () => {
    const custom = createDefaultStockChartPreferences()
    custom.heightRatios['kline|volume|macd'] = [0.5, 0.3, 0.2]

    const hidden = setAuxiliaryChartType(custom, 'slot3', 'hidden')
    const shown = setAuxiliaryChartType(hidden, 'slot3', 'macd')

    expect(chartCompositionKey(hidden)).toBe('kline|volume')
    expect(shown.heightRatios['kline|volume|macd']).toEqual([0.5, 0.3, 0.2])
  })
})

describe('useStockChartPreferences draft state', () => {
  it('拖动草稿只更新内存，commit 后才写入持久偏好源', async () => {
    const persisted = ref<StockChartPreferences>(createDefaultStockChartPreferences())
    const source = computed({
      get: () => persisted.value,
      set: (value) => {
        persisted.value = value
      },
    })
    const model = useStockChartPreferences(source, ref(true))

    model.beginRatioDraft()
    model.updateRatioDraft([0.5, 0.3, 0.2])
    expect(model.currentRatios.value).toEqual([0.5, 0.3, 0.2])
    expect(persisted.value.heightRatios['kline|volume|macd']).toEqual([0.6, 0.2, 0.2])

    model.commitRatioDraft()
    await nextTick()
    expect(persisted.value.heightRatios['kline|volume|macd']).toEqual([0.5, 0.3, 0.2])
  })

  it('偏好尚未 hydrate 时只派生安全值，不主动改写源', async () => {
    const raw = ref({
      slot2: 'broken',
      slot3: 'hidden',
      heightRatios: {},
    } as unknown as StockChartPreferences)
    const hydrated = ref(false)
    const source = computed({
      get: () => raw.value,
      set: (value) => {
        raw.value = value
      },
    })
    const model = useStockChartPreferences(source, hydrated)

    expect(model.preferences.value.slot2).toBe('volume')
    expect(raw.value.slot2).toBe('broken')

    hydrated.value = true
    await nextTick()
    expect(raw.value.slot2).toBe('volume')
  })
})
