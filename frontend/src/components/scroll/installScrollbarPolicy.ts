import { inputModality, subscribeInputModality } from '@/utils/inputModality'
import { SCROLLBAR_IDLE_MS, scrollbarOverflow, scrollbarVisible, type ScrollbarActivity } from './scrollbarPolicy'

const ROOT = '.el-scrollbar'
const OVERLAY = '.el-overlay, .el-popper, [id^="el-popper-container-"]'
const geometryUpdates = new WeakMap<HTMLElement, () => void>()

/** 填充布局的 view 高度固定，由容器通过公开实例 API 更新轨道几何，不读取 Vue 私有实例。 */
export function registerScrollbarGeometry(root: HTMLElement, update: () => void): () => void {
  geometryUpdates.set(root, update)
  return () => { if (geometryUpdates.get(root) === update) geometryUpdates.delete(root) }
}

/** 只适配库内结构；页面及自建容器不消费这些选择器。 */
export function bindScrollbarPolicy(root: HTMLElement): (() => void) | undefined {
  const viewport = root.querySelector<HTMLElement>(':scope > .el-scrollbar__wrap')
  const content = viewport?.querySelector<HTMLElement>(':scope > .el-scrollbar__view')
  if (!viewport || !content) return
  const state: ScrollbarActivity = {
    hovered: false, keyboardFocused: false, scrolling: false, dragging: false,
  }
  let idleTimer: ReturnType<typeof setTimeout> | undefined
  let frame = 0
  let disposed = false
  let suspended = false
  let scrollIntentUntil = 0
  const originalTabindex = viewport.getAttribute('tabindex')
  const cleanups: Array<() => void> = []
  function listen(target: EventTarget, name: string, callback: EventListener,
    options: boolean | AddEventListenerOptions = false) {
    target.addEventListener(name, callback, options)
    cleanups.push(() => target.removeEventListener(name, callback, options))
  }
  function clearIdle() {
    clearTimeout(idleTimer)
    idleTimer = undefined
  }
  function update() {
    if (disposed) return
    const overflow = scrollbarOverflow(viewport!)
    // 缓存页面隐藏或浮层关闭后不保留瞬态显示；再次激活由尺寸观察重新判定。
    if (!root.isConnected || viewport!.clientWidth === 0 || viewport!.clientHeight === 0) {
      clearIdle()
      scrollIntentUntil = 0
      Object.assign(state, { hovered: false, keyboardFocused: false, scrolling: false, dragging: false })
    }
    root.dataset.appScrollX = String(overflow.x)
    root.dataset.appScrollY = String(overflow.y)
    root.dataset.appScrollVisible = String(!suspended && scrollbarVisible(state))
    if (originalTabindex == null) {
      // 表单/导航已有焦点入口时不插入额外 Tab 停靠点，保留弹窗原有初始焦点。
      const hasControls = content!.querySelector(
        'button:not([disabled]), input:not([disabled]):not([type="hidden"]), '
        + 'select:not([disabled]), textarea:not([disabled]), a[href], '
        + '[tabindex]:not([tabindex="-1"])',
      )
      if ((overflow.x || overflow.y) && !hasControls) viewport!.setAttribute('tabindex', '0')
      else viewport!.removeAttribute('tabindex')
    }
  }
  function scheduleUpdate() {
    if (frame || disposed) return
    frame = requestAnimationFrame(() => {
      frame = 0
      geometryUpdates.get(root)?.()
      update()
    })
  }
  function syncKeyboardFocus() {
    const focused = document.activeElement
    state.keyboardFocused = !inputModality.isPointerInteraction()
      && focused instanceof Element && root.contains(focused)
      && focused.closest(ROOT) === root
    update()
  }
  function markScrollIntent() {
    suspended = false
    scrollIntentUntil = Date.now() + SCROLLBAR_IDLE_MS
  }
  const enter = ((event: PointerEvent) => {
    if (event.pointerType === 'touch') return
    if (state.hovered && !suspended) return
    suspended = false
    state.hovered = true
    update()
  }) as EventListener
  listen(root, 'pointerenter', enter)
  // 从其他窗口返回时指针可能仍在区域内，没有新的 enter；首次移动恢复悬停。
  listen(root, 'pointermove', enter)
  listen(root, 'pointerleave', () => { state.hovered = false; update() })
  listen(root, 'focusin', () => { suspended = false; syncKeyboardFocus() })
  listen(root, 'focusout', () => { queueMicrotask(() => { if (!disposed) syncKeyboardFocus() }) })
  listen(root, 'keydown', ((event: KeyboardEvent) => {
    suspended = false
    if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'PageUp', 'PageDown', 'Home', 'End', ' '].includes(event.key)) {
      markScrollIntent()
    }
    syncKeyboardFocus()
  }) as EventListener)
  // scroll 本身不携带来源；先记录滚轮/触摸意图，再由实际滚动开启短暂显示。
  // 允许意图冒泡到外层，以承接嵌套区域到边界后的原生滚动链。
  listen(viewport, 'wheel', markScrollIntent, { passive: true })
  listen(viewport, 'touchmove', markScrollIntent, { passive: true })
  listen(root, 'pointerdown', ((event: PointerEvent) => {
    state.keyboardFocused = false
    const target = event.target
    if (event.button === 0 && target instanceof Element
      && target.closest('.el-scrollbar__bar')?.parentElement === root) {
      state.dragging = true
      markScrollIntent()
    }
    update()
  }) as EventListener, true)
  function endDrag() {
    if (!state.dragging) return
    state.dragging = false
    update()
  }
  listen(document, 'pointerup', endDrag)
  listen(document, 'pointercancel', endDrag)
  listen(document, 'mouseup', endDrag)
  listen(viewport, 'scroll', () => {
    // 缓存激活、焦点定位、尺寸收敛及程序恢复位置均可能触发 scroll，不能凭此点亮轨道。
    // 已开始的用户滚动持续刷新期限，覆盖惯性滚动和拖出区域后的后续事件。
    if (!state.dragging && !state.scrolling && Date.now() >= scrollIntentUntil) {
      update()
      return
    }
    suspended = false
    state.scrolling = true
    clearIdle()
    idleTimer = setTimeout(() => { idleTimer = undefined; state.scrolling = false; update() }, SCROLLBAR_IDLE_MS)
    update()
  })
  const stopModality = subscribeInputModality(() => {
    suspended = true
    scrollIntentUntil = 0
    clearIdle()
    Object.assign(state, { hovered: false, keyboardFocused: false, scrolling: false, dragging: false })
    update()
  })
  const resize = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(scheduleUpdate)
  resize?.observe(viewport)
  resize?.observe(content)
  const observedChildren = new Set<Element>()
  function observeChildren() {
    // flex/grid 的填充 view 本身不随内容伸长；直接内容块的尺寸变化仍须更新滑块。
    for (const child of observedChildren) {
      if (child.parentElement === content) continue
      resize?.unobserve(child)
      observedChildren.delete(child)
    }
    for (const child of content!.children) {
      if (observedChildren.has(child)) continue
      observedChildren.add(child)
      resize?.observe(child)
    }
  }
  observeChildren()
  const mutation = new MutationObserver(() => { observeChildren(); scheduleUpdate() })
  mutation.observe(content, { childList: true, subtree: true, characterData: true })
  root.dataset.appScrollManaged = ''
  state.hovered = !!window.matchMedia?.('(hover: hover) and (pointer: fine)').matches
    && root.matches(':hover')
  syncKeyboardFocus()
  return () => {
    if (disposed) return
    disposed = true
    clearIdle()
    cancelAnimationFrame(frame)
    resize?.disconnect()
    mutation.disconnect()
    stopModality()
    cleanups.forEach(stop => stop())
    if (originalTabindex == null) viewport.removeAttribute('tabindex')
    for (const key of ['appScrollManaged', 'appScrollX', 'appScrollY', 'appScrollVisible']) delete root.dataset[key]
  }
}

/** 全站仅安装一次；初始扫描及新增子树注册，移除时释放，不在滚动事件里扫描 DOM。 */
export function installScrollbarPolicy(appRoot: HTMLElement): () => void {
  const registered = new Map<HTMLElement, () => void>()
  function scan(node: Node) {
    if (!(node instanceof HTMLElement)) return
    const ancestor = node.closest<HTMLElement>(ROOT)
    const roots = [ ...(ancestor ? [ancestor] : []), ...node.querySelectorAll<HTMLElement>(ROOT) ]
    for (const root of roots) {
      if (registered.has(root) || !root.isConnected) continue
      const stop = bindScrollbarPolicy(root)
      if (stop) registered.set(root, stop)
    }
  }
  function prune() {
    for (const [root, stop] of registered) {
      if (root.isConnected) continue
      stop()
      registered.delete(root)
    }
  }
  const observer = new MutationObserver(mutations => {
    for (const mutation of mutations) for (const node of mutation.addedNodes) scan(node)
    prune()
  })
  scan(appRoot)
  observer.observe(appRoot, { childList: true, subtree: true })
  const bodyObserver = new MutationObserver(mutations => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (node instanceof HTMLElement && node.matches(OVERLAY)) scan(node)
      }
    }
    prune()
  })
  for (const node of document.body.children) if (node.matches(OVERLAY)) scan(node)
  bodyObserver.observe(document.body, { childList: true })
  return () => {
    observer.disconnect()
    bodyObserver.disconnect()
    for (const stop of registered.values()) stop()
    registered.clear()
  }
}
