import { onBeforeUnmount, onMounted } from 'vue'
import { inputModality, subscribeInputModality } from '@/utils/inputModality'

/** 保留提示消费者接口，统一输入来源与窗口失焦清理。 */
export function useTooltipInputModality(onSuspend?: () => void) {
  let stop: (() => void) | undefined
  onMounted(() => { stop = subscribeInputModality(onSuspend) })
  onBeforeUnmount(() => stop?.())
  return inputModality
}
