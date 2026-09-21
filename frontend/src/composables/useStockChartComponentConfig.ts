import { computed, isRef, ref, watch, type Ref, type WritableComputedRef } from 'vue'
import {
  constrainWorkspaceRatios,
  type StockChartWorkspaceSample,
} from '@/components/stock-chart/workspaceOptions'
import {
  normalizeStockChartPreferences,
  useStockChartPreferences,
  type AuxiliaryChartSlot,
  type StockChartPreferences,
} from '@/composables/useStockChartPreferences'
import type { StockChartRatioSample } from '@/layout/stockChartRatioProfiles'
import { useDefaultedSessionValue } from '@/composables/useDefaultedSessionValue'
import {
  normalizeStockAnalysisPreferences,
  type StockAnalysisComponentPreferences,
} from '@/composables/useStockAnalysisSession'
import {
  normalizeSectorAnalysisPreferences,
  type SectorAnalysisComponentPreferences,
} from '@/composables/useSectorAnalysisPreferences'

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
  const stockAnalysis = computed<StockAnalysisComponentPreferences>({
    get: () => normalizeStockAnalysisPreferences(access.componentValueOf(slotId, 'stockAnalysis')),
    set: (value) => access.setComponentKnob(slotId, 'stockAnalysis', value),
  })
  const sectorAnalysis = computed<SectorAnalysisComponentPreferences>({
    get: () => normalizeSectorAnalysisPreferences(access.componentValueOf(slotId, 'sectorAnalysis')),
    set: (value) => access.setComponentKnob(slotId, 'sectorAnalysis', value),
  })
  const measurementOperationsExpanded = useDefaultedSessionValue(computed(() => (
    access.componentValueOf(slotId, 'measurementOperationsExpanded') === true
  )))
  const returnMeasurementMode = useDefaultedSessionValue(computed<'latest' | 'range'>(() => (
    access.componentValueOf(slotId, 'returnMeasurementMode') === 'range' ? 'range' : 'latest'
  )))
  const workspaceSample = ref<StockChartRatioSample | null>(null)
  const workspaceMeasurement = ref<StockChartWorkspaceSample | null>(null)
  const configuredWorkspaceSample = ref<StockChartRatioSample | null>(null)

  function refreshConfiguredWorkspaceSample(): void {
    const sample = workspaceMeasurement.value
    if (!sample) {
      configuredWorkspaceSample.value = null
      return
    }
    configuredWorkspaceSample.value = {
      width: sample.width,
      height: sample.height,
      ratios: constrainWorkspaceRatios(
        preferences.configuredRatios.value,
        sample.minimumRatios,
      ),
    }
  }

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

  function handleWorkspaceResize(sample?: StockChartWorkspaceSample): void {
    if (!sample) {
      workspaceMeasurement.value = null
      workspaceSample.value = null
      configuredWorkspaceSample.value = null
      return
    }
    workspaceMeasurement.value = {
      ...sample,
      ratios: [...sample.ratios],
      minimumRatios: [...sample.minimumRatios],
    }
    workspaceSample.value = {
      width: sample.width,
      height: sample.height,
      ratios: [...sample.ratios],
    }
    preferences.setWorkspaceSize(sample)
    refreshConfiguredWorkspaceSample()
  }

  watch(preferences.configuredRatios, refreshConfiguredWorkspaceSample, { deep: true })

  /** 抽屉分别读取已配置基线和当前拖动样本；离开工作区后不保留过期样本。 */
  const componentRuntimeValueOf: ComponentRuntimeValueOf = (candidateSlotId, field) => {
    if (candidateSlotId !== slotId) return undefined
    if (field === 'stockChart') {
      return preferences.preferencesWithCurrentRatioProfile(workspaceSample.value ?? undefined)
    }
    if (field === 'stockChartConfigured') {
      return preferences.preferencesWithCurrentRatioProfile(
        configuredWorkspaceSample.value ?? undefined,
      )
    }
    if (field === 'stockChartRatioSample') return workspaceSample.value ?? undefined
    return undefined
  }

  return {
    ...preferences,
    stockAnalysis,
    sectorAnalysis,
    measurementOperationsExpanded,
    returnMeasurementMode,
    setAuxiliaryChart,
    handleRatioDraft,
    handleRatioCommit,
    handleWorkspaceResize,
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
