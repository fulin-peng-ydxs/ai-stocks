import type { DirectiveBinding, ObjectDirective } from 'vue'

type RevealKey = string | boolean | null
const active = new WeakMap<HTMLElement, () => void>()

/** 只增强显现效果，不延迟渲染、不持有旧内容，也不改变缓存或布局结构。 */
function reveal(el: HTMLElement, binding: DirectiveBinding<RevealKey>): void {
  active.get(el)?.()
  if (!binding.value) return
  const preference = window.matchMedia?.('(prefers-reduced-motion: reduce)')
  if (preference?.matches) return
  const style = getComputedStyle(el)
  const duration = Number.parseFloat(style.getPropertyValue(
    binding.arg === 'page' ? '--app-motion-page' : '--app-motion-content',
  ))
  if (!Number.isFinite(duration) || duration <= 0) return

  // 工作区宿主为 display:contents；对其真实根节点显现，兼容多根页面与 KeepAlive。
  const targets = style.display === 'contents' ? Array.from(el.children) : [el]
  // 页面进入只做轻量位移；图表、表格内容保持原位，避免数值阅读与画布测量受扰。
  const frames: Keyframe[] = binding.arg === 'page'
    ? [{ opacity: 0.35, translate: `0 ${style.getPropertyValue('--app-motion-distance').trim() || '4px'}` },
      { opacity: 1, translate: '0 0' }]
    : [{ opacity: 0.35 }, { opacity: 1 }]
  const animations = targets.filter((target) => typeof target.animate === 'function').map(
    (target) => target.animate(frames, {
      duration,
      easing: style.getPropertyValue('--app-motion-ease').trim() || 'ease-out',
    }),
  )
  if (!animations.length) return
  const cleanup = () => {
    animations.forEach((animation) => animation.cancel())
    preference?.removeEventListener('change', cleanup)
    if (active.get(el) === cleanup) active.delete(el)
  }
  active.set(el, cleanup)
  preference?.addEventListener('change', cleanup)
  // cancel() 会拒绝 finished；allSettled 同时处理快速切换、卸载与正常完成。
  void Promise.allSettled(animations.map((animation) => animation.finished)).then(cleanup)
}

export const vReveal: ObjectDirective<HTMLElement, RevealKey> = {
  mounted: reveal,
  updated(el, binding) {
    if (binding.value !== binding.oldValue) reveal(el, binding)
  },
  beforeUnmount(el) { active.get(el)?.() },
}
