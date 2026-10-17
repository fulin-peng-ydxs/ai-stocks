import { computed, reactive } from 'vue'
import { getAccessToken, readAuth } from '@/api/authToken'
import { createGlobalPreferenceSync } from './useGlobalPreferenceSync'

const PREFIX = 'ai-stocks:workspace-tabs'
const state = reactive({ collapsed: true, hydrated: false, dirty: false, edited: false })
let storageKey = ''
let revision = 0
let saveChain = Promise.resolve()

function currentStorageKey(): string {
  const auth = readAuth()
  return auth.accessToken && auth.user?.id
    ? `${PREFIX}:${auth.tenant?.id || 'default'}:${auth.user.id}`
    : `${PREFIX}:anonymous`
}

function normalize(value: unknown): { collapsed: boolean } | undefined {
  const collapsed = (value as { collapsed?: unknown } | null)?.collapsed
  return typeof collapsed === 'boolean' ? { collapsed } : undefined
}

function readLocal(): { collapsed: boolean; pending: boolean } {
  try {
    const raw = JSON.parse(localStorage.getItem(storageKey) || 'null')
    return { collapsed: normalize(raw)?.collapsed ?? true, pending: raw?.pending === true }
  } catch { return { collapsed: true, pending: false } }
}

function persistLocal(): void {
  try { localStorage.setItem(storageKey, JSON.stringify({ collapsed: state.collapsed, pending: state.dirty })) }
  catch { /* 本地缓存不可用时继续使用账号偏好。 */ }
}

// 账号偏好落 PG；本地只作按租户/用户隔离的首屏与离线回退。
const sync = createGlobalPreferenceSync<{ collapsed: boolean }>({
  prefKey: 'workspace-tabs',
  identityKey: currentStorageKey,
  isHydrated: () => state.hydrated,
  snapshot: () => ({ collapsed: state.collapsed }),
  // 没有远端记录时沿用本地/默认值；只由下面的串行入口写入用户选择。
  normalize: value => normalize(value) ?? { collapsed: state.collapsed },
  // 手动选择不能被更早开始的读取覆盖，即使保存已先于读取完成。
  applyRemote(value) { if (!state.dirty && !state.edited) state.collapsed = value.collapsed },
  persistLocal,
  onIdentityChange({ identityKey }) {
    storageKey = identityKey
    saveChain = Promise.resolve()
    revision += 1
    const local = readLocal()
    state.collapsed = local.collapsed
    state.hydrated = false
    state.dirty = local.pending
    state.edited = local.pending
  },
  onNoToken() { state.hydrated = true },
  onLoadSuccess() {
    state.hydrated = true
    if (state.dirty) void saveCurrent()
  },
  onLoadError() { state.hydrated = true },
})

function saveCurrent(): Promise<void> {
  const requestKey = storageKey
  const requestRevision = revision
  const token = getAccessToken()
  const value = { collapsed: state.collapsed }
  // 连续切换按顺序落库；旧版本尚未发出时直接跳过，避免慢写覆盖最后一次选择。
  saveChain = saveChain.then(async () => {
    if (requestKey !== storageKey || requestKey !== currentStorageKey()
      || requestRevision !== revision || token !== getAccessToken()) return
    const saved = await sync.saveNow(value)
    if (saved && requestKey === storageKey && requestRevision === revision) {
      state.dirty = false
      persistLocal()
    }
  })
  return saveChain
}

export function useWorkspaceTabPreferences() {
  void sync.syncOnce()
  return {
    collapsed: computed(() => state.collapsed),
    setCollapsed(value: boolean) {
      sync.ensureIdentity()
      state.collapsed = value
      state.dirty = true
      state.edited = true
      revision += 1
      // 先记待同步意图，再立即写回；立刻刷新也不能被旧的远端值反向覆盖。
      persistLocal()
      void saveCurrent()
    },
  }
}

export function resetWorkspaceTabPreferencesForTests(): void {
  sync.resetForTests()
  storageKey = ''
  revision += 1
  saveChain = Promise.resolve()
  state.collapsed = true
  state.hydrated = false
  state.dirty = false
  state.edited = false
}
