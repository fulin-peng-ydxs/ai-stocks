// 全局主题（白天/夜间）：模块级单例状态，切换 html.dark 类，持久化到 localStorage。
import { ref } from 'vue'

const STORAGE_KEY = 'ai-stocks-theme'
const isDark = ref(false)

function apply(v: boolean) {
  document.documentElement.classList.toggle('dark', v)
}

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
  localStorage.setItem(STORAGE_KEY, isDark.value ? 'dark' : 'light')
  apply(isDark.value)
}

export function useTheme() {
  return { isDark, toggleTheme }
}
