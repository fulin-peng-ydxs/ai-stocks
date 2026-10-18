/** 唯一行为参数；视觉参数在 scrollbar.css 的主题 token 中维护。 */
export const SCROLLBAR_IDLE_MS = 800
export const SCROLLBAR_OVERFLOW_EPSILON = 1

export interface ScrollbarActivity {
  hovered: boolean
  keyboardFocused: boolean
  scrolling: boolean
  dragging: boolean
}

export function scrollbarVisible(state: ScrollbarActivity): boolean {
  return state.hovered || state.keyboardFocused || state.scrolling || state.dragging
}

export function scrollbarOverflow(viewport: HTMLElement): { x: boolean; y: boolean } {
  return {
    x: viewport.clientWidth > 0
      && viewport.scrollWidth - viewport.clientWidth > SCROLLBAR_OVERFLOW_EPSILON,
    y: viewport.clientHeight > 0
      && viewport.scrollHeight - viewport.clientHeight > SCROLLBAR_OVERFLOW_EPSILON,
  }
}
