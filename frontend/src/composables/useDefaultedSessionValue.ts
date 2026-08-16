import { ref, watch, type Ref } from 'vue'

export interface DefaultedSessionValueOptions<T> {
  shouldSync?: (value: T) => boolean
  onSynced?: (value: T) => void
}

/**
 * 把持久化/配置层默认值单向投影为页面会话值。
 * 页面控件只绑定返回的 ref；修改会话值不会反写默认值。
 */
export function useDefaultedSessionValue<T>(
  defaultValue: Readonly<Ref<T>>,
  options: DefaultedSessionValueOptions<T> = {},
): Ref<T> {
  const sessionValue = ref(defaultValue.value) as Ref<T>
  watch(defaultValue, (value) => {
    if (options.shouldSync && !options.shouldSync(value)) return
    sessionValue.value = value
    options.onSynced?.(value)
  })
  return sessionValue
}
