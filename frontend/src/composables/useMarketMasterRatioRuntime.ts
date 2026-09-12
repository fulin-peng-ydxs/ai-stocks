import { ref } from 'vue'
import type { MasterDetailRatioSample } from '@/layout/masterDetailRatioProfiles'

/**
 * 汇总行情主从工作台的会话分栏比例，供共享设置抽屉读取“页面当前比例”。
 * 持久化仍由组件配置层负责，避免四个消费页各自维护映射规则。
 */
export function useMarketMasterRatioRuntime() {
  const currentMasterRatio = ref<number | undefined>()
  const currentMasterRatioSample = ref<MasterDetailRatioSample | undefined>()

  function setCurrentMasterRatio(value: number): void {
    if (Number.isFinite(value)) currentMasterRatio.value = Math.round(value)
  }

  function setCurrentMasterRatioSample(value: MasterDetailRatioSample | undefined): void {
    currentMasterRatioSample.value = value
    if (value) setCurrentMasterRatio(value.ratio)
  }

  function componentRuntimeValueOf(slotId: string, field: string): unknown {
    if (slotId !== 'workspace') return undefined
    if (field === 'masterRatio') return currentMasterRatio.value
    if (field === 'masterRatioProfiles') return currentMasterRatioSample.value
    return undefined
  }

  return {
    currentMasterRatio,
    currentMasterRatioSample,
    setCurrentMasterRatio,
    setCurrentMasterRatioSample,
    componentRuntimeValueOf,
  }
}
