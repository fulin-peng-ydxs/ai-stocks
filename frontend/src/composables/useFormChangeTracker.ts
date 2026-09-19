import { computed, ref, type ComputedRef } from 'vue'

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue)
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, stableValue(item)]),
    )
  }
  return value
}

function fingerprint(value: unknown): string {
  return JSON.stringify(stableValue(value))
}

export interface FormChangeTracker {
  hasChanges: ComputedRef<boolean>
  captureBaseline: () => void
  clearBaseline: () => void
}

/**
 * 以页面实际提交负载为快照跟踪编辑变化。页面完成回填或保存成功后应重新记录基线；
 * 尚未记录基线时保持不可保存，避免异步初始化期间误提交半成品数据。
 */
export function useFormChangeTracker(snapshot: () => unknown): FormChangeTracker {
  const baseline = ref<string | null>(null)
  const current = computed(() => fingerprint(snapshot()))
  const hasChanges = computed(() => baseline.value !== null && current.value !== baseline.value)

  function captureBaseline(): void {
    baseline.value = current.value
  }

  function clearBaseline(): void {
    baseline.value = null
  }

  return { hasChanges, captureBaseline, clearBaseline }
}
