import { onBeforeUnmount, onDeactivated, ref, watch } from 'vue'
import { useTooltipInputModality } from './useTooltipInputModality'
import { APP_HOVER_TOOLTIP_DELAY_MS } from '@/components/overflow/tooltipTiming'

const CONTENT_ENTRY_GRACE_MS = 180

/** 说明浮层共用的鼠标静止判定，键盘焦点不等待。 */
export function useHoverIntent(isDisabled: () => boolean, allowsContentEntry: () => boolean) {
  const visible = ref(false)
  const modality = useTooltipInputModality(reset, onLayoutChange)
  let pointerInside = false
  let pointer: { reference: HTMLElement; x: number; y: number } | null = null
  let contentInside = false
  let focused = false
  let showTimer: ReturnType<typeof setTimeout> | null = null
  let hideTimer: ReturnType<typeof setTimeout> | null = null

  function clearShow(): void {
    if (showTimer == null) return
    clearTimeout(showTimer)
    showTimer = null
  }

  function clearHide(): void {
    if (hideTimer == null) return
    clearTimeout(hideTimer)
    hideTimer = null
  }

  function reset(): void {
    clearShow()
    clearHide()
    pointerInside = false
    pointer = null
    contentInside = false
    focused = false
    visible.value = false
  }

  function rememberPointer(event?: MouseEvent): void {
    if (event?.currentTarget instanceof HTMLElement) {
      pointer = { reference: event.currentTarget, x: event.clientX, y: event.clientY }
    }
  }

  function onLayoutChange(): void {
    const previous = pointer
    reset()
    // 切屏会分阶段通知。取消旧定位后重新核对真实命中，不能丢掉刚进入且已静止的鼠标意图。
    // 失焦/后台仍走 reset，不恢复；元素移走、被遮挡或移除时也不重弹。
    if (!previous || document.hidden || !previous.reference.isConnected) return
    const hit = document.elementFromPoint?.(previous.x, previous.y)
    if (!hit || !previous.reference.contains(hit)) return
    pointer = previous
    pointerInside = true
    scheduleShow()
  }

  function scheduleShow(): void {
    clearShow()
    if (isDisabled() || focused || contentInside) return
    showTimer = setTimeout(() => {
      showTimer = null
      if (pointerInside && !isDisabled()) visible.value = true
    }, APP_HOVER_TOOLTIP_DELAY_MS)
  }

  function onMouseEnter(event?: MouseEvent): void {
    if (isDisabled()) return
    rememberPointer(event)
    pointerInside = true
    clearHide()
    scheduleShow()
  }

  function onMouseMove(event?: MouseEvent): void {
    if (isDisabled() || focused || contentInside) return
    rememberPointer(event)
    pointerInside = true
    if (visible.value) visible.value = false
    scheduleShow()
  }

  function onMouseLeave(): void {
    pointerInside = false
    pointer = null
    clearShow()
    if (focused || contentInside) return
    if (!visible.value) return
    if (!allowsContentEntry()) {
      visible.value = false
      return
    }
    clearHide()
    hideTimer = setTimeout(() => {
      hideTimer = null
      if (!pointerInside && !contentInside && !focused) visible.value = false
    }, CONTENT_ENTRY_GRACE_MS)
  }

  function onFocusIn(): void {
    if (modality.isPointerInteraction()) return
    if (isDisabled()) return
    focused = true
    clearShow()
    clearHide()
    visible.value = true
  }

  function onPointerDown(): void {
    reset()
    modality.markPointer()
  }

  function onKeyDown(event: KeyboardEvent): void {
    modality.markKeyboard()
    if (event.key === 'Escape') reset()
  }

  function onReferenceClick(): void {
    // 链接在路由切换前仍会短暂保留旧浮层；点击时先清理，不能等页面停用。
    reset()
  }

  function onFocusOut(event: FocusEvent): void {
    if (event.relatedTarget instanceof Node
      && event.currentTarget instanceof Node
      && event.currentTarget.contains(event.relatedTarget)) return
    focused = false
    if (contentInside) return
    visible.value = false
    if (pointerInside) scheduleShow()
  }

  function onContentEnter(): void {
    contentInside = true
    clearHide()
  }

  function onContentLeave(): void {
    contentInside = false
    if (!pointerInside && !focused) visible.value = false
  }

  watch(isDisabled, (disabled) => { if (disabled) reset() })
  // 工作区会缓存页面；离开时收起传送到 body 的浮层，避免锚点隐藏后漂到视口角落。
  onDeactivated(reset)
  onBeforeUnmount(reset)

  return {
    visible,
    onMouseEnter,
    onMouseMove,
    onMouseLeave,
    onFocusIn,
    onPointerDown,
    onKeyDown,
    onReferenceClick,
    onFocusOut,
    onContentEnter,
    onContentLeave,
  }
}
