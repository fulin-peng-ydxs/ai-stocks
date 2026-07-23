import { computed, ref, watch, type Ref, type WritableComputedRef } from 'vue'

export type ChartType = 'kline' | 'volume' | 'macd'
export type AuxiliaryChartType = Exclude<ChartType, 'kline'> | 'hidden'
export type AuxiliaryChartSlot = 'slot2' | 'slot3'
export type ChartCompositionKey =
  | 'kline'
  | 'kline|volume'
  | 'kline|macd'
  | 'kline|volume|macd'
  | 'kline|macd|volume'

export interface StockChartPreferences {
  slot2: AuxiliaryChartType
  slot3: AuxiliaryChartType
  heightRatios: Record<ChartCompositionKey, number[]>
}

const AUXILIARY_TYPES: readonly AuxiliaryChartType[] = ['volume', 'macd', 'hidden']
const COMPOSITION_KEYS: readonly ChartCompositionKey[] = [
  'kline',
  'kline|volume',
  'kline|macd',
  'kline|volume|macd',
  'kline|macd|volume',
]
const DEFAULT_RATIOS: Record<ChartCompositionKey, readonly number[]> = {
  kline: [1],
  'kline|volume': [0.75, 0.25],
  'kline|macd': [0.75, 0.25],
  'kline|volume|macd': [0.6, 0.2, 0.2],
  'kline|macd|volume': [0.6, 0.2, 0.2],
}
const RATIO_SUM_EPSILON = 1e-6

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function isAuxiliaryChartType(value: unknown): value is AuxiliaryChartType {
  return AUXILIARY_TYPES.includes(value as AuxiliaryChartType)
}

function cloneDefaultRatios(key: ChartCompositionKey): number[] {
  return [...DEFAULT_RATIOS[key]]
}

export function createDefaultStockChartPreferences(): StockChartPreferences {
  return {
    slot2: 'volume',
    slot3: 'macd',
    heightRatios: Object.fromEntries(
      COMPOSITION_KEYS.map((key) => [key, cloneDefaultRatios(key)]),
    ) as Record<ChartCompositionKey, number[]>,
  }
}

export function normalizeHeightRatios(
  value: unknown,
  key: ChartCompositionKey,
): number[] {
  const fallback = cloneDefaultRatios(key)
  if (!Array.isArray(value) || value.length !== fallback.length) return fallback
  if (!value.every((item) => typeof item === 'number' && Number.isFinite(item) && item > 0)) {
    return fallback
  }
  const total = value.reduce((sum, item) => sum + item, 0)
  if (Math.abs(total - 1) > RATIO_SUM_EPSILON) return fallback
  return value.map((item) => item / total)
}

export function normalizeStockChartPreferences(value: unknown): StockChartPreferences {
  const defaults = createDefaultStockChartPreferences()
  if (!isRecord(value)) return defaults

  const slot2Valid = isAuxiliaryChartType(value.slot2)
  const slot3Valid = isAuxiliaryChartType(value.slot3)
  let slot2 = slot2Valid ? value.slot2 as AuxiliaryChartType : defaults.slot2
  let slot3 = slot3Valid ? value.slot3 as AuxiliaryChartType : defaults.slot3
  if (!slot2Valid && slot3Valid && slot2 === slot3 && slot3 !== 'hidden') {
    slot2 = slot3 === 'volume' ? 'macd' : 'volume'
  }
  if (slot2Valid && !slot3Valid && slot2 === slot3 && slot2 !== 'hidden') {
    slot3 = slot2 === 'volume' ? 'macd' : 'volume'
  }
  // 存量重复值无法判断最后修改的是哪个槽位，按需求回到完整默认组合。
  const hasDuplicate = slot2Valid && slot3Valid && slot2 !== 'hidden' && slot2 === slot3
  const ratios = isRecord(value.heightRatios) ? value.heightRatios : {}

  return {
    slot2: hasDuplicate ? defaults.slot2 : slot2,
    slot3: hasDuplicate ? defaults.slot3 : slot3,
    heightRatios: Object.fromEntries(
      COMPOSITION_KEYS.map((key) => [key, normalizeHeightRatios(ratios[key], key)]),
    ) as Record<ChartCompositionKey, number[]>,
  }
}

export function visibleChartTypes(value: unknown): ChartType[] {
  const preferences = normalizeStockChartPreferences(value)
  const types: ChartType[] = ['kline']
  if (preferences.slot2 !== 'hidden') types.push(preferences.slot2)
  if (preferences.slot3 !== 'hidden') types.push(preferences.slot3)
  return types
}

export function chartCompositionKey(value: unknown): ChartCompositionKey {
  return visibleChartTypes(value).join('|') as ChartCompositionKey
}

export function setAuxiliaryChartType(
  value: unknown,
  slot: AuxiliaryChartSlot,
  nextType: unknown,
): StockChartPreferences {
  const preferences = normalizeStockChartPreferences(value)
  if (!isAuxiliaryChartType(nextType)) return preferences

  const otherSlot: AuxiliaryChartSlot = slot === 'slot2' ? 'slot3' : 'slot2'
  const previous = preferences[slot]
  if (nextType !== 'hidden' && preferences[otherSlot] === nextType) {
    // 目标类型已被占用时交换；原槽位为 hidden 时，另一槽随交换隐藏。
    preferences[otherSlot] = previous
  }
  preferences[slot] = nextType
  return normalizeStockChartPreferences(preferences)
}

function samePreferences(left: unknown, right: StockChartPreferences): boolean {
  return JSON.stringify(left) === JSON.stringify(right)
}

export function useStockChartPreferences(
  source: WritableComputedRef<StockChartPreferences>,
  hydrated: Ref<boolean>,
) {
  const normalized = computed(() => normalizeStockChartPreferences(source.value))
  const composition = computed(() => chartCompositionKey(normalized.value))
  const draftKey = ref<ChartCompositionKey | null>(null)
  const draftRatios = ref<number[] | null>(null)
  const currentRatios = computed(() => (
    draftKey.value === composition.value && draftRatios.value
      ? [...draftRatios.value]
      : [...normalized.value.heightRatios[composition.value]]
  ))

  function clearDraft(): void {
    draftKey.value = null
    draftRatios.value = null
  }

  function setSlotType(slot: AuxiliaryChartSlot, nextType: unknown): void {
    clearDraft()
    source.value = setAuxiliaryChartType(source.value, slot, nextType)
  }

  function beginRatioDraft(): number[] {
    draftKey.value = composition.value
    draftRatios.value = [...normalized.value.heightRatios[composition.value]]
    return [...draftRatios.value]
  }

  function updateRatioDraft(value: unknown): number[] {
    const key = draftKey.value ?? composition.value
    draftKey.value = key
    draftRatios.value = normalizeHeightRatios(value, key)
    return [...draftRatios.value]
  }

  function commitHeightRatios(
    value: unknown,
    key: ChartCompositionKey = composition.value,
  ): void {
    const preferences = normalizeStockChartPreferences(source.value)
    source.value = {
      ...preferences,
      heightRatios: {
        ...preferences.heightRatios,
        [key]: normalizeHeightRatios(value, key),
      },
    }
  }

  function commitRatioDraft(): void {
    if (draftKey.value && draftRatios.value && draftKey.value === composition.value) {
      commitHeightRatios(draftRatios.value, draftKey.value)
    }
    clearDraft()
  }

  // 远端同步完成前只提供安全派生值，不写 source，避免本地修复误触 dirty-before-hydrate。
  watch(
    [() => source.value, hydrated],
    ([value, isHydrated]) => {
      if (!isHydrated) return
      const next = normalizeStockChartPreferences(value)
      if (!samePreferences(value, next)) source.value = next
    },
    { deep: true, immediate: true },
  )

  return {
    preferences: normalized,
    visibleTypes: computed(() => visibleChartTypes(normalized.value)),
    compositionKey: composition,
    currentRatios,
    draftRatios,
    setSlotType,
    beginRatioDraft,
    updateRatioDraft,
    commitRatioDraft,
    cancelRatioDraft: clearDraft,
    commitHeightRatios,
  }
}
