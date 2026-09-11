import { onBeforeUnmount, onMounted, readonly, ref } from 'vue'

/** 与 app-viewport 容器查询共享应用根的布局尺寸，禁止把屏幕像素用于重排判断。 */
export function useLayoutViewport() {
  const width = ref(0)
  const height = ref(0)
  let observer: ResizeObserver | undefined

  function measure(): void {
    const root = document.getElementById('app')
    width.value = root?.clientWidth ?? 0
    height.value = root?.clientHeight ?? 0
  }

  onMounted(() => {
    measure()
    const root = document.getElementById('app')
    if (root && typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(measure)
      observer.observe(root)
    }
    window.addEventListener('resize', measure)
  })
  onBeforeUnmount(() => {
    observer?.disconnect()
    window.removeEventListener('resize', measure)
  })

  return { width: readonly(width), height: readonly(height) }
}
