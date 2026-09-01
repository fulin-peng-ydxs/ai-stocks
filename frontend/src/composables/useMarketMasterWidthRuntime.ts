import { ref } from 'vue'

/**
 * 汇总行情主从工作台的会话宽度，供共享设置抽屉读取“页面当前宽度”。
 * 持久化仍由组件配置层负责，避免四个消费页各自维护映射规则。
 */
export function useMarketMasterWidthRuntime() {
  const currentMasterWidth = ref<number | undefined>()

  function setCurrentMasterWidth(value: number): void {
    if (Number.isFinite(value)) currentMasterWidth.value = Math.round(value)
  }

  function componentRuntimeValueOf(slotId: string, field: string): unknown {
    return slotId === 'workspace' && field === 'masterWidth'
      ? currentMasterWidth.value
      : undefined
  }

  return { currentMasterWidth, setCurrentMasterWidth, componentRuntimeValueOf }
}
