type SuspendHandler = () => void
let pointerInteraction = false
const consumers = new Set<SuspendHandler>()

function markPointer(): void { pointerInteraction = true }
function markKeyboard(event: KeyboardEvent): void {
  if (!event.metaKey && !event.altKey && !event.ctrlKey) pointerInteraction = false
}
function suspend(): void {
  pointerInteraction = true
  for (const handler of consumers) handler()
}
function onVisibilityChange(): void {
  if (document.visibilityState === 'hidden') suspend()
}

/** 提示与滚动条共用输入来源及窗口挂起信号，按订阅生命周期注册全局监听。 */
export function subscribeInputModality(onSuspend: SuspendHandler = () => {}): () => void {
  if (consumers.size === 0) {
    document.addEventListener('pointerdown', markPointer, true)
    document.addEventListener('keydown', markKeyboard, true)
    window.addEventListener('blur', suspend)
    document.addEventListener('visibilitychange', onVisibilityChange)
  }
  consumers.add(onSuspend)
  return () => {
    consumers.delete(onSuspend)
    if (consumers.size) return
    document.removeEventListener('pointerdown', markPointer, true)
    document.removeEventListener('keydown', markKeyboard, true)
    window.removeEventListener('blur', suspend)
    document.removeEventListener('visibilitychange', onVisibilityChange)
    pointerInteraction = false
  }
}

export const inputModality = {
  isPointerInteraction: () => pointerInteraction,
  markPointer,
  markKeyboard: () => { pointerInteraction = false },
}
