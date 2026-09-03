import { computed, isRef, ref, type Ref, type WritableComputedRef } from 'vue'
import {
  normalizeStockChartPreferences,
  useStockChartPreferences,
  type AuxiliaryChartSlot,
  type StockChartPreferences,
} from '@/composables/useStockChartPreferences'

interface StockChartComponentConfigAccess {
  slotId?: string
  componentValueOf: (slotId: string, field: string) => unknown
  setComponentKnob: (slotId: string, field: string, value: unknown) => void
  hydrated: Ref<boolean>
}

export type ComponentRuntimeValueOf = (slotId: string, field: string) => unknown

/**
 * 把股票多图工作区的组合、默认比例与拖动会话态接到统一组件配置层。
 * 页面只声明 chart slot，不再为同一组件维护平行的 usePageSettings 字段。
 */
export function useStockChartComponentConfig(access: StockChartComponentConfigAccess) {
  const slotId = access.slotId ?? 'chart'
  const source = computed<StockChartPreferences>({
    get: () => normalizeStockChartPreferences(access.componentValueOf(slotId, 'stockChart')),
    set: (value) => access.setComponentKnob(slotId, 'stockChart', value),
  }) as WritableComputedRef<StockChartPreferences>
  // 页面单测或离线壳可能只提供基础组件访问器；缺少远端水合 ref 时按已就绪处理。
  const hydrated = isRef(access.hydrated) ? access.hydrated : ref(true)
  const preferences = useStockChartPreferences(source, hydrated)

  function setAuxiliaryChart(slot: AuxiliaryChartSlot, value: string | number | boolean): void {
    preferences.setSlotType(slot, value)
  }

  function handleRatioDraft(ratios: number[]): void {
    preferences.updateRatioDraft(ratios)
  }

  function handleRatioCommit(ratios: number[]): void {
    preferences.updateRatioDraft(ratios)
    preferences.commitRatioDraft()
  }

  /** 设置抽屉可据此将工作区当前拖动比例保存为该组件实例的默认比例。 */
  const componentRuntimeValueOf: ComponentRuntimeValueOf = (candidateSlotId, field) => {
    if (candidateSlotId !== slotId || field !== 'stockChart') return undefined
    const value = preferences.preferences.value
    return {
      ...value,
      heightRatios: {
        ...value.heightRatios,
        [preferences.compositionKey.value]: [...preferences.currentRatios.value],
      },
    }
  }

  return {
    ...preferences,
    setAuxiliaryChart,
    handleRatioDraft,
    handleRatioCommit,
    componentRuntimeValueOf,
  }
}

/** 多个组件实例的运行时值解析器按顺序合并，供同一设置抽屉消费。 */
export function composeComponentRuntimeValueOf(
  ...resolvers: Array<ComponentRuntimeValueOf | undefined>
): ComponentRuntimeValueOf {
  return (slotId, field) => {
    for (const resolver of resolvers) {
      const value = resolver?.(slotId, field)
      if (value !== undefined) return value
    }
    return undefined
  }
}
