// 全局主题（白天/夜间）：模块级单例状态，首屏读 localStorage，登录后同步 PG 用户偏好。
import { ref } from 'vue'
import { getAccessToken } from '@/api/authToken'
import { createGlobalPreferenceSync } from './useGlobalPreferenceSync'

const STORAGE_KEY = 'ai-stocks-theme'
const PENDING_SYNC_KEY = 'ai-stocks-theme-pending-sync'
const isDark = ref(false)
type ThemePreference = { mode: 'dark' | 'light' }

function apply(v: boolean) {
  document.documentElement.classList.toggle('dark', v)
}

function persistLocal() {
  localStorage.setItem(STORAGE_KEY, isDark.value ? 'dark' : 'light')
}

const themePreferenceSync = createGlobalPreferenceSync<ThemePreference>({
  prefKey: 'theme',
  snapshot: () => ({ mode: isDark.value ? 'dark' : 'light' }),
  normalize(value) {
    const mode = (value as { mode?: unknown } | undefined)?.mode
    return mode === 'dark' || mode === 'light' ? { mode } : undefined
  },
  applyRemote(value) {
    isDark.value = value.mode === 'dark'
    persistLocal()
    apply(isDark.value)
  },
})

export function initTheme() {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved) {
    isDark.value = saved === 'dark'
  } else {
    isDark.value = window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
  }
  apply(isDark.value)
}

export function toggleTheme() {
  isDark.value = !isDark.value
  persistLocal()
  apply(isDark.value)
  // 登录页的手动选择代表本次明确意图。先留在本地，登录成功后必须优先写回账号，
  // 不能被账号中上一次保存的远端模式反向覆盖。
  localStorage.setItem(PENDING_SYNC_KEY, '1')
  if (getAccessToken()) {
    void themePreferenceSync.saveNow().then((saved) => {
      if (saved) localStorage.removeItem(PENDING_SYNC_KEY)
    })
  }
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
  return { isDark, toggleTheme, syncThemePreference }
}
