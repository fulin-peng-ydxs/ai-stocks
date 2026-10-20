import { onBeforeUnmount, onMounted } from 'vue'
import { inputModality, subscribeInputModality } from '@/utils/inputModality'

const layoutConsumers = new Set<() => void>()
function resetLayoutHints(): void {
  for (const reset of layoutConsumers) reset()
}

/** 说明与截断提示共用一个布局监听；useDisplayScale 在切屏/比例变化后也派发 resize。 */
function subscribeLayoutReset(reset: () => void): () => void {
  if (!layoutConsumers.size) window.addEventListener('resize', resetLayoutHints)
  layoutConsumers.add(reset)
  return () => {
    layoutConsumers.delete(reset)
    if (!layoutConsumers.size) window.removeEventListener('resize', resetLayoutHints)
  }
}

/** 保留提示消费者接口，统一输入来源、窗口失焦和布局变化后的瞬态清理。 */
export function useTooltipInputModality(onSuspend?: () => void, onLayoutChange = onSuspend) {
  let stop: (() => void) | undefined
  let stopLayout: (() => void) | undefined
  onMounted(() => {
    stop = subscribeInputModality(onSuspend)
    if (onLayoutChange) stopLayout = subscribeLayoutReset(onLayoutChange)
  })
  onBeforeUnmount(() => { stop?.(); stopLayout?.() })
  return inputModality
}
