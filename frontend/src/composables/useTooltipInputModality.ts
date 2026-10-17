import { onBeforeUnmount, onMounted } from 'vue'

let consumers = 0
let pointerInteraction = false
function markPointer(): void { pointerInteraction = true }
function markKeyboard(): void { pointerInteraction = false }

/** 显式说明与截断宿主共享输入来源；焦点归还仍由原控件负责。 */
export function useTooltipInputModality() {
  onMounted(() => {
    if (consumers++ > 0) return
    document.addEventListener('pointerdown', markPointer, true)
    document.addEventListener('keydown', markKeyboard, true)
  })
  onBeforeUnmount(() => {
    if (--consumers > 0) return
    document.removeEventListener('pointerdown', markPointer, true)
    document.removeEventListener('keydown', markKeyboard, true)
    pointerInteraction = false
  })
  return { isPointerInteraction: () => pointerInteraction, markPointer, markKeyboard }
}
