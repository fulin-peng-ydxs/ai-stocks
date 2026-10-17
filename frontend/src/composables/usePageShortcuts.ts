import { onActivated, onBeforeUnmount, onDeactivated, onMounted } from 'vue'
import { acceptsPageShortcut } from '@/utils/keyboard'

export interface PageShortcut {
  key: string
  enabled?: () => boolean
  run: () => unknown | Promise<unknown>
}

/** 随页面缓存生命周期注册；异步动作完成前不接受第二次快捷命令。 */
export function usePageShortcuts(
  shortcuts: PageShortcut[],
  options: { enabled: () => boolean; onError: (error: unknown) => void },
) {
  let listening = false
  let pending = false
  async function onKey(event: KeyboardEvent) {
    if (pending || !options.enabled() || !acceptsPageShortcut(event)) return
    const shortcut = shortcuts.find(item => item.key.toLowerCase() === event.key.toLowerCase())
    if (!shortcut || (shortcut.enabled && !shortcut.enabled())) return
    event.preventDefault()
    pending = true
    try { await shortcut.run() }
    catch (error) { options.onError(error) }
    finally { pending = false }
  }
  function attach() {
    if (listening) return
    window.addEventListener('keydown', onKey)
    listening = true
  }
  function detach() {
    window.removeEventListener('keydown', onKey)
    listening = false
  }
  onMounted(attach)
  onActivated(attach)
  onDeactivated(detach)
  onBeforeUnmount(detach)
}
