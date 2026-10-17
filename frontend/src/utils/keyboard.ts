/** 项目自定义键盘行为的共同边界；原生控件继续交给浏览器/组件库。 */
export function acceptsKeyboardEvent(event: KeyboardEvent, allowRepeat = false): boolean {
  return !event.defaultPrevented && !event.isComposing && event.keyCode !== 229
    && !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey
    && (allowRepeat || !event.repeat)
}

export function isKeyboardDisabled(element: HTMLElement): boolean {
  return !!element.closest('[disabled], [aria-disabled="true"], [aria-busy="true"], [inert], .is-loading')
}

/** 仅确认当前单行输入；keydown 避免输入法结束后的 keyup 误提交。 */
export function submitOnEnter(event: KeyboardEvent, submit: () => unknown): void {
  if (event.key !== 'Enter' || !acceptsKeyboardEvent(event)) return
  const target = event.target
  if (!(target instanceof HTMLInputElement) || isKeyboardDisabled(target)) return
  event.preventDefault()
  submit()
}

export function keyboardRangeValue(
  event: KeyboardEvent,
  value: number,
  options: { axis: 'horizontal' | 'vertical'; step: number; min: number; max: number },
): number | undefined {
  if (!acceptsKeyboardEvent(event, true) || event.target !== event.currentTarget) return
  const { axis, step, min, max } = options
  let next: number
  if (event.key === (axis === 'horizontal' ? 'ArrowLeft' : 'ArrowUp')) next = value - step
  else if (event.key === (axis === 'horizontal' ? 'ArrowRight' : 'ArrowDown')) next = value + step
  else if (event.key === 'Home') next = min
  else if (event.key === 'End') next = max
  else return
  event.preventDefault()
  return Math.min(max, Math.max(min, next))
}

/** 页面快捷键不能抢输入、控件自身的键盘行为或前景弹层。 */
export function acceptsPageShortcut(event: KeyboardEvent): boolean {
  if (!acceptsKeyboardEvent(event) || document.hidden) return false
  const target = event.target
  if (target instanceof Element && target.closest(
    'input, textarea, select, button, a[href], [contenteditable]:not([contenteditable="false"]), '
    + '[tabindex], [role="button"], [role="combobox"], [role="slider"], [role="separator"]',
  )) return false
  return !Array.from(document.querySelectorAll<HTMLElement>(
    '[role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"], .el-picker-panel',
  )).some(element => element.getClientRects().length > 0
    && getComputedStyle(element).visibility !== 'hidden')
}
