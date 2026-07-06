// 登录态持久化事实源（localStorage）——多租户 RBAC stage2·T7。
// 独立于 Pinia store 与 axios client，避免「client ↔ store ↔ api」循环依赖：
// - client 请求拦截读 token、401 时清态，都走这里；
// - auth store 写入/读取也走这里，保持内存态与持久态一致。

const STORAGE_KEY = 'ai-stocks-auth'

export interface AuthSnapshot {
  accessToken: string
  refreshToken: string
  user: { id: string; account: string; email?: string | null; status?: string } | null
  tenant: { id: string } | null
  role: string
}

const EMPTY: AuthSnapshot = { accessToken: '', refreshToken: '', user: null, tenant: null, role: '' }

export function readAuth(): AuthSnapshot {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? { ...EMPTY, ...JSON.parse(raw) } : { ...EMPTY }
  } catch {
    return { ...EMPTY }
  }
}

export function writeAuth(snap: AuthSnapshot): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(snap))
}

export function clearAuth(): void {
  localStorage.removeItem(STORAGE_KEY)
}

export function getAccessToken(): string {
  return readAuth().accessToken
}

export function getRefreshToken(): string {
  return readAuth().refreshToken
}

export function updateTokens(accessToken: string, refreshToken: string): void {
  const snap = readAuth()
  writeAuth({ ...snap, accessToken, refreshToken })
}
