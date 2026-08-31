import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

/** 将组件生命周期内的媒体查询监听统一为只读响应式状态。 */
export function useMediaQuery(query: string): Readonly<Ref<boolean>> {
  const matches = ref(false)
  let queryList: MediaQueryList | null = null

  function syncMatches(event?: MediaQueryListEvent): void {
    matches.value = event?.matches ?? queryList?.matches ?? false
  }

  onMounted(() => {
    if (typeof window.matchMedia !== 'function') return
    queryList = window.matchMedia(query)
    syncMatches()
    queryList.addEventListener('change', syncMatches)
  })

  onBeforeUnmount(() => {
    queryList?.removeEventListener('change', syncMatches)
    queryList = null
  })

  return matches
}
