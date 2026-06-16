import { computed, reactive, watch } from 'vue'

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function isObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function mergeDefaults<T>(defaults: T, saved: unknown): T {
  if (Array.isArray(defaults)) return Array.isArray(saved) ? (saved as T) : clone(defaults)
  if (isObject(defaults)) {
    const out: Record<string, unknown> = {}
    const src = isObject(saved) ? saved : {}
    for (const [key, value] of Object.entries(defaults)) out[key] = mergeDefaults(value, src[key])
    return out as T
  }
  return (saved === undefined ? defaults : saved) as T
}

function replaceReactive<T extends Record<string, unknown>>(target: T, source: T) {
  for (const key of Object.keys(target)) delete target[key]
  Object.assign(target, source)
}

export function usePageSettings<T extends Record<string, unknown>>(pageKey: string, defaults: T) {
  const storageKey = `ai-stocks:page-settings:${pageKey}`
  let saved: unknown
  try {
    const raw = localStorage.getItem(storageKey)
    saved = raw ? JSON.parse(raw) : undefined
  } catch {
    saved = undefined
  }

  const settings = reactive(mergeDefaults(defaults, saved)) as T

  watch(settings, (value) => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(value))
    } catch {
      /* ignore */
    }
  }, { deep: true })

  const isDirty = computed(() => JSON.stringify(settings) !== JSON.stringify(defaults))

  function reset() {
    replaceReactive(settings, clone(defaults))
  }

  return { settings, isDirty, reset }
}
