import { inject, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { WORKSPACE_RESIZE_ACTIVE } from '@/layout/workspaceResizeContext'

/** 父级分栏拖动时合并尺寸刷新，结束后只按最终尺寸执行一次。 */
export function useDeferredWorkspaceResize(resize: () => void): () => void {
  const workspaceResizeActive = inject(WORKSPACE_RESIZE_ACTIVE, ref(false))
  let pending = false
  let scheduled = false
  let disposed = false

  function schedulePendingResize(): void {
    if (scheduled) return
    scheduled = true
    void nextTick(() => {
      scheduled = false
      if (disposed || !pending) return
      if (workspaceResizeActive.value) return
      pending = false
      resize()
    })
  }

  function requestResize(): void {
    if (disposed) return
    if (workspaceResizeActive.value) {
      pending = true
      return
    }
    pending = false
    resize()
  }

  watch(workspaceResizeActive, (active) => {
    if (!active && pending) schedulePendingResize()
  })
  onBeforeUnmount(() => {
    disposed = true
    pending = false
  })

  return requestResize
}
