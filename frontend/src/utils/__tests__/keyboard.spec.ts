// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { acceptsPageShortcut, keyboardRangeValue, submitOnEnter } from '../keyboard'

afterEach(() => { document.body.innerHTML = ''; vi.restoreAllMocks() })
function dispatch(element: HTMLElement, handler: (e: KeyboardEvent) => void, init: KeyboardEventInit) {
  element.addEventListener('keydown', handler, { once: true })
  const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init })
  element.dispatchEvent(event)
  return event
}

describe('键盘边界', () => {
  it('输入确认只接受单行输入的无修饰 Enter，输入法和多行文本保留原行为', () => {
    const input = document.createElement('input'), area = document.createElement('textarea')
    const submit = vi.fn()
    const handler = (event: KeyboardEvent) => submitOnEnter(event, submit)
    dispatch(input, handler, { key: 'Enter', isComposing: true })
    dispatch(input, handler, { key: 'Enter', keyCode: 229 })
    dispatch(input, handler, { key: 'Enter', ctrlKey: true })
    dispatch(area, handler, { key: 'Enter' })
    expect(submit).not.toHaveBeenCalled()
    expect(dispatch(input, handler, { key: 'Enter' }).defaultPrevented).toBe(true)
    expect(submit).toHaveBeenCalledOnce()
  })
  it('范围控制支持对应方向、Home/End、长按与夹紧，组合键不接管', () => {
    const el = document.createElement('div')
    let value: number | undefined
    const handle = (event: KeyboardEvent) => { value = keyboardRangeValue(event, 40, { axis: 'horizontal', min: 30, max: 60, step: 25 }) }
    for (const [key, expected] of [['ArrowLeft', 30], ['ArrowRight', 60], ['Home', 30], ['End', 60], ['ArrowUp', undefined]] as const) {
      dispatch(el, handle, { key, repeat: true }); expect(value).toBe(expected)
    }
    dispatch(el, handle, { key: 'ArrowLeft', altKey: true }); expect(value).toBeUndefined()
  })
  it.each(['input', 'textarea', 'select', 'button', 'a', 'div'])('页面快捷键让位于输入与交互目标 %s', tag => {
    const target = document.createElement(tag)
    if (tag === 'a') target.setAttribute('href', '#')
    if (tag === 'div') target.setAttribute('contenteditable', 'true')
    let accepted = true
    dispatch(target, e => { accepted = acceptsPageShortcut(e) }, { key: 'b' })
    expect(accepted).toBe(false)
  })
  it('已消费事件和可见弹层阻止快捷键，隐藏弹层不阻止', () => {
    const modal = document.createElement('div'); modal.setAttribute('role', 'dialog'); document.body.append(modal)
    const event = new KeyboardEvent('keydown', { key: 'b', cancelable: true })
    expect(acceptsPageShortcut(event)).toBe(true)
    vi.spyOn(modal, 'getClientRects').mockReturnValue([{}] as unknown as DOMRectList)
    expect(acceptsPageShortcut(event)).toBe(false)
    modal.remove(); event.preventDefault()
    expect(acceptsPageShortcut(event)).toBe(false)
  })
})
