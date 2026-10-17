import { onBeforeUnmount, onMounted } from 'vue'

let consumers = 0
let pointerInteraction = false
const suspendHandlers = new Set<() => void>()
function markPointer(): void { pointerInteraction = true }
function markKeyboard(): void { pointerInteraction = false }

function suspend(): void {
  // 桌面切换快捷键会先触发 keydown；恢复窗口焦点不能误当作新的键盘阅读意图。
  markPointer()
  for (const handler of suspendHandlers) handler()
}

function onVisibilityChange(): void {
  if (document.visibilityState === 'hidden') suspend()
}

/** 显式说明与截断宿主共享输入来源；焦点归还仍由原控件负责。 */
export function useTooltipInputModality(onSuspend?: () => void) {
  onMounted(() => {
    if (onSuspend) suspendHandlers.add(onSuspend)
    if (consumers++ > 0) return
    document.addEventListener('pointerdown', markPointer, true)
    document.addEventListener('keydown', markKeyboard, true)
    window.addEventListener('blur', suspend)
    document.addEventListener('visibilitychange', onVisibilityChange)
  })
  onBeforeUnmount(() => {
    if (onSuspend) suspendHandlers.delete(onSuspend)
    if (--consumers > 0) return
    document.removeEventListener('pointerdown', markPointer, true)
    document.removeEventListener('keydown', markKeyboard, true)
    window.removeEventListener('blur', suspend)
    document.removeEventListener('visibilitychange', onVisibilityChange)
    pointerInteraction = false
  })
  return { isPointerInteraction: () => pointerInteraction, markPointer, markKeyboard }
}
