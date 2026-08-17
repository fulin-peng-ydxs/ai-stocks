import { computed, type Ref } from 'vue'
import { normalizePageSize } from '@/constants/pagination'
import { useDefaultedSessionValue } from '@/composables/useDefaultedSessionValue'

export interface ComponentPageSizeSessionOptions {
  resolveDefault: () => unknown
  fallback?: number
  normalize?: (value: unknown, fallback?: number) => number
  shouldSync?: (value: number) => boolean
  resetPage: () => void
  reload: () => unknown
}

export interface ComponentPageSizeSession {
  defaultPageSize: Readonly<Ref<number>>
  pageSize: Ref<number>
  changePageSize: (value: number) => void
}

/**
 * 统一组件配置每页条数到页面分页会话的单向投影与重载编排。
 * 抽屉默认值和页面临时选择保持分离，两种变更都统一归到第一页后重新加载。
 */
export function useComponentPageSizeSession(
  options: ComponentPageSizeSessionOptions,
): ComponentPageSizeSession {
  const normalize = options.normalize ?? normalizePageSize
  const configuredPageSize = computed(() => (
    normalize(options.resolveDefault(), options.fallback)
  ))

  const resetAndReload = () => {
    options.resetPage()
    void options.reload()
  }

  const pageSize = useDefaultedSessionValue(configuredPageSize, {
    shouldSync: options.shouldSync,
    onSynced: resetAndReload,
  })

  const changePageSize = (value: number) => {
    pageSize.value = normalize(value, configuredPageSize.value)
    resetAndReload()
  }

  return { defaultPageSize: configuredPageSize, pageSize, changePageSize }
}
