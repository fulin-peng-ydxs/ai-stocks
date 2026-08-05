// 全局主题（白天/夜间/跟随系统）：模块级单例状态，首屏读 localStorage，登录后同步 PG 用户偏好。
// 用户意图（themeMode: light|dark|system）与最终生效的明暗（isDark）解耦：
// system 时由 prefers-color-scheme 驱动 isDark，并监听系统变化实时切换；isDark 语义不变，下游消费者零改动。
import { ref } from 'vue'
import { getAccessToken } from '@/api/authToken'
import { createGlobalPreferenceSync } from './useGlobalPreferenceSync'

export type ThemeMode = 'light' | 'dark' | 'system'
type ThemePreference = { mode: ThemeMode }

const STORAGE_KEY = 'ai-stocks-theme'
const PENDING_SYNC_KEY = 'ai-stocks-theme-pending-sync'
const themeMode = ref<ThemeMode>('light')
const isDark = ref(false)

function apply(v: boolean) {
  document.documentElement.classList.toggle('dark', v)
}

function systemPrefersDark(): boolean {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
}

function resolveDark(mode: ThemeMode): boolean {
  return mode === 'system' ? systemPrefersDark() : mode === 'dark'
}

let systemMediaQuery: MediaQueryList | null = null

function onSystemChange() {
  if (themeMode.value !== 'system') return
  isDark.value = resolveDark(themeMode.value)
  apply(isDark.value)
}

/** system 态挂载 prefers-color-scheme 监听（系统切黑/白时实时跟随），其余态卸载。 */
function attachSystemListener() {
  if (themeMode.value !== 'system') {
    if (systemMediaQuery) {
      systemMediaQuery.removeEventListener?.('change', onSystemChange)
      systemMediaQuery = null
    }
    return
  }
  if (systemMediaQuery) return
  const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
  if (!mq) return
  mq.addEventListener?.('change', onSystemChange)
  systemMediaQuery = mq
}

function persistLocal() {
  localStorage.setItem(STORAGE_KEY, themeMode.value)
}

const themePreferenceSync = createGlobalPreferenceSync<ThemePreference>({
  prefKey: 'theme',
  snapshot: () => ({ mode: themeMode.value }),
  normalize(value) {
    const mode = (value as { mode?: unknown } | undefined)?.mode
    return mode === 'dark' || mode === 'light' || mode === 'system' ? { mode } : undefined
  },
  applyRemote(value) {
    themeMode.value = value.mode
    isDark.value = resolveDark(value.mode)
    persistLocal()
    apply(isDark.value)
    attachSystemListener()
  },
})

export function initTheme() {
  const saved = localStorage.getItem(STORAGE_KEY)
  themeMode.value =
    saved === 'dark' || saved === 'light' || saved === 'system' ? saved : 'system'
  isDark.value = resolveDark(themeMode.value)
  apply(isDark.value)
  attachSystemListener()
}

export function setThemeMode(mode: ThemeMode) {
  themeMode.value = mode
  isDark.value = resolveDark(mode)
  persistLocal()
  apply(isDark.value)
  attachSystemListener()
  // 登录页的手动选择代表本次明确意图。先留在本地，登录成功后必须优先写回账号，
  // 不能被账号中上一次保存的远端模式反向覆盖。
  localStorage.setItem(PENDING_SYNC_KEY, '1')
  if (getAccessToken()) {
    void themePreferenceSync.saveNow().then((saved) => {
      if (saved) localStorage.removeItem(PENDING_SYNC_KEY)
    })
  }
}

/** 快捷开关：无论从哪个意图态翻转，都落到「当前可见的反色」这一显式意图。 */
export function toggleTheme() {
  setThemeMode(isDark.value ? 'light' : 'dark')
}

/** 登录/注册请求发出前锁定当前可见模式，保证鉴权后的首屏与登录页连续。 */
export function carryCurrentThemeIntoSession() {
  localStorage.setItem(PENDING_SYNC_KEY, '1')
}

export async function syncThemePreference() {
  if (localStorage.getItem(PENDING_SYNC_KEY) === '1') {
    // 保存失败时保留本地选择和 pending 标记，下次鉴权成功后重试；此时不再读取远端，
    // 避免网络抖动也让页面从用户刚选的白天模式跳回夜间模式。
    const saved = await themePreferenceSync.saveNow()
    if (saved) localStorage.removeItem(PENDING_SYNC_KEY)
    return
  }
  await themePreferenceSync.syncOnce()
}

export function useTheme() {
  return { isDark, themeMode, toggleTheme, setThemeMode, syncThemePreference }
}
