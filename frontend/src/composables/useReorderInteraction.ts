import { nextTick, onBeforeUnmount, onDeactivated, ref, shallowRef, watch, type Ref } from 'vue'
import { acceptsKeyboardEvent, reorderKey, type ReorderKey } from '@/utils/keyboard'

type Direction = Exclude<ReorderKey, 'confirm' | 'cancel' | 'leave'>
interface ReorderOptions<T> {
  root: Ref<HTMLElement | undefined>
  disabled: () => boolean
  revision: () => unknown[]
  initialTarget: (key: string) => T | null
  pointerTarget: (x: number, y: number, key: string) => T | null
  keyboardTarget: (key: string, current: T | null, direction: Direction) => T | null
  label: (key: string) => string
  describe: (key: string, target: T) => string
  commit: (key: string, target: T) => void
}

/** 平面列表和树共用输入会话与资源清理；目标解析、移动规则及保存留在各自所有者。 */
export function useReorderInteraction<T>(options: ReorderOptions<T>) {
  const activeKey = ref<string | null>(null)
  const destination = shallowRef<T | null>(null)
  const announcement = ref('')
  let pointerId: number | null = null
  let capture: HTMLElement | null = null
  let startX = 0, startY = 0, pointerX = 0, pointerY = 0
  let moved = false, frame = 0
  let scrollport: HTMLElement | null = null

  function cancel(): void {
    window.removeEventListener('pointermove', pointerMove)
    window.removeEventListener('pointerup', pointerUp)
    window.removeEventListener('pointercancel', cancel)
    window.removeEventListener('keydown', escape, true)
    window.removeEventListener('blur', cancel)
    document.removeEventListener('visibilitychange', cancel)
    cancelAnimationFrame(frame)
    const previousCapture = capture, previousPointer = pointerId
    pointerId = null
    capture = null
    scrollport = null
    activeKey.value = null
    destination.value = null
    if (previousPointer !== null && previousCapture?.hasPointerCapture?.(previousPointer)) {
      previousCapture.releasePointerCapture(previousPointer)
    }
  }

  function focus(key: string): void {
    const handle = Array.from(options.root.value?.querySelectorAll<HTMLElement>('[data-reorder-key]') ?? [])
      .find(row => row.dataset.reorderKey === key)?.querySelector<HTMLButtonElement>('.app-drag-handle')
    handle?.focus({ preventScroll: true })
  }

  function commit(): void {
    const key = activeKey.value, target = destination.value
    cancel()
    if (options.disabled() || key === null || target === null) return
    options.commit(key, target)
    announcement.value = options.describe(key, target)
    void nextTick(() => focus(key))
  }

  function listenForCancel(): void {
    window.addEventListener('keydown', escape, true)
    window.addEventListener('blur', cancel)
    document.addEventListener('visibilitychange', cancel)
  }

  function updateDestination(): void {
    if (activeKey.value !== null) {
      destination.value = options.pointerTarget(pointerX, pointerY, activeKey.value)
    }
  }

  function autoScroll(): void {
    if (pointerId === null) return
    if (moved && scrollport) {
      const rect = scrollport.getBoundingClientRect()
      const top = Math.max(0, rect.top), bottom = Math.min(window.innerHeight, rect.bottom)
      if (pointerY >= top && pointerY <= bottom && pointerX >= rect.left && pointerX <= rect.right) {
        const delta = pointerY < top + 40 ? -10 : pointerY > bottom - 40 ? 10 : 0
        if (delta) { scrollport.scrollTop += delta; updateDestination() }
      }
    }
    frame = requestAnimationFrame(autoScroll)
  }

  function pointerDown(event: PointerEvent, key: string): void {
    if (options.disabled() || event.button !== 0 || event.isPrimary === false) return
    cancel()
    activeKey.value = key
    destination.value = options.initialTarget(key)
    startX = pointerX = event.clientX
    startY = pointerY = event.clientY
    moved = false
    pointerId = event.pointerId
    capture = event.currentTarget as HTMLElement
    capture.focus()
    capture.setPointerCapture?.(pointerId)
    scrollport = options.root.value?.parentElement ?? null
    while (scrollport && !/(auto|scroll)/.test(getComputedStyle(scrollport).overflowY)) {
      scrollport = scrollport.parentElement
    }
    window.addEventListener('pointermove', pointerMove, { passive: false })
    window.addEventListener('pointerup', pointerUp)
    window.addEventListener('pointercancel', cancel)
    listenForCancel()
    frame = requestAnimationFrame(autoScroll)
    event.preventDefault()
  }

  function pointerMove(event: PointerEvent): void {
    if (event.pointerId !== pointerId) return
    pointerX = event.clientX
    pointerY = event.clientY
    moved ||= Math.hypot(pointerX - startX, pointerY - startY) >= 5
    if (!moved) return
    event.preventDefault()
    updateDestination()
  }

  function pointerUp(event: PointerEvent): void {
    if (event.pointerId !== pointerId) return
    if (moved) {
      pointerX = event.clientX
      pointerY = event.clientY
      updateDestination()
      commit()
    } else cancel()
  }

  function escape(event: KeyboardEvent): void {
    if (event.key !== 'Escape' || activeKey.value === null || !acceptsKeyboardEvent(event)) return
    // 前景复合浮层优先处理 Escape；排序取消不截走下拉、日期或对话框的退出键。
    const foreground = Array.from(document.querySelectorAll<HTMLElement>(
      '[role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"], .el-picker-panel',
    )).some(element => element.getClientRects().length > 0
      && getComputedStyle(element).visibility !== 'hidden'
      && !element.contains(options.root.value ?? null))
    if (!foreground) { event.preventDefault(); event.stopPropagation() }
    cancel()
    announcement.value = '已取消排序'
  }

  function keydown(event: KeyboardEvent, key: string): void {
    if (options.disabled() || pointerId !== null) return
    const command = reorderKey(event)
    if (!command) return
    if (command === 'leave') { cancel(); return }
    if (command === 'confirm') {
      event.preventDefault()
      if (activeKey.value !== null) commit()
      else {
        activeKey.value = key
        destination.value = options.initialTarget(key)
        listenForCancel()
        announcement.value = `已拿起${options.label(key)}，使用方向键选择位置，空格确认，Esc 取消`
      }
    } else if (activeKey.value !== null && command === 'cancel') {
      event.preventDefault()
      cancel()
      announcement.value = '已取消排序'
    } else if (activeKey.value !== null && command !== 'cancel') {
      event.preventDefault()
      destination.value = options.keyboardTarget(activeKey.value, destination.value, command)
      if (destination.value !== null) announcement.value = options.describe(activeKey.value, destination.value)
    }
  }

  function blur(): void { if (pointerId === null) cancel() }
  watch(() => [options.disabled(), ...options.revision()], cancel)
  onBeforeUnmount(cancel)
  onDeactivated(cancel)
  return { activeKey, destination, announcement, pointerDown, keydown, blur, cancel, focus }
}
