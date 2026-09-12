import { readAuth } from '@/api/authToken'

const PAGE_SESSION_PREFIX = 'ai-stocks:page-session:v1'

function identityParts(): { tenantId: string; userId: string } {
  const auth = readAuth()
  return {
    tenantId: auth.tenant?.id || 'anonymous',
    userId: auth.user?.id || 'anonymous',
  }
}

/** 当前 Tab 内按页面命名空间、租户和用户隔离的会话键。 */
export function pageSessionStorageKey(namespace: string): string {
  const { tenantId, userId } = identityParts()
  return `${PAGE_SESSION_PREFIX}:${namespace}:${tenantId}:${userId}`
}

export function readPageSession<T>(namespace: string, legacyKeys: string[] = []): T | null {
  try {
    const currentKey = pageSessionStorageKey(namespace)
    const raw = sessionStorage.getItem(currentKey)
    if (raw) return JSON.parse(raw) as T
    for (const legacyKey of legacyKeys) {
      const legacyRaw = sessionStorage.getItem(legacyKey)
      if (!legacyRaw) continue
      const value = JSON.parse(legacyRaw) as T
      sessionStorage.setItem(currentKey, JSON.stringify(value))
      sessionStorage.removeItem(legacyKey)
      return value
    }
    return null
  } catch {
    return null
  }
}

export function writePageSession<T>(namespace: string, value: T): void {
  try {
    sessionStorage.setItem(pageSessionStorageKey(namespace), JSON.stringify(value))
  } catch {
    /* 浏览器拒绝存储时退化为当前组件/Store 内存会话。 */
  }
}

export function removePageSession(namespace: string, legacyKeys: string[] = []): void {
  try {
    sessionStorage.removeItem(pageSessionStorageKey(namespace))
    legacyKeys.forEach((key) => sessionStorage.removeItem(key))
  } catch {
    /* ignore */
  }
}

/** 退出登录或切换身份时清理本应用所有 Tab 会话，不影响同源其他 sessionStorage。 */
export function clearAllPageSessions(legacyPrefixes: string[] = []): void {
  try {
    for (let index = sessionStorage.length - 1; index >= 0; index -= 1) {
      const key = sessionStorage.key(index)
      if (!key) continue
      if (
        key.startsWith(`${PAGE_SESSION_PREFIX}:`)
        || legacyPrefixes.some((prefix) => key.startsWith(prefix))
      ) sessionStorage.removeItem(key)
    }
  } catch {
    /* ignore */
  }
}
