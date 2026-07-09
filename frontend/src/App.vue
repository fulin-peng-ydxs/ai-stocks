<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Calendar, Clock, Refresh } from '@element-plus/icons-vue'
import { useTheme, toggleTheme } from '@/composables/useTheme'
import { effectivePresetTokens, setPresetOverrides, useLayoutPreset, type LayoutPresetKey } from '@/layout'
import { listLayoutPresets } from '@/api/layout'
import {
  getDataStatus,
  listTasks,
  STATUS_LABEL,
  TASK_LABEL,
  type AsyncTask,
  type DataStatus,
  type TaskStatus,
} from '@/api/data'
import { useAuthStore } from '@/stores/auth'
import { useTradeDates } from '@/composables/useTradeDates'
import BrandMark from '@/components/BrandMark.vue'
import SideMenu from '@/components/SideMenu.vue'

const { isDark } = useTheme()
const { activePresetKey, options: presetOptions, setLayoutPreset } = useLayoutPreset()
const userDrawerVisible = ref(false)
const appearanceDrawerVisible = ref(false)
// 全屏独立壳（stage2·T7）：登录页等 meta.fullscreen 路由脱离主框架（侧栏/顶栏）单独渲染
const route = useRoute()
const router = useRouter()
const isFullscreen = computed(() => Boolean(route.meta.fullscreen))

// 顶栏用户区（stage2·T9）：身份来自 auth store（登录态从 localStorage 自 hydrate）
const auth = useAuthStore()
const displayName = computed(() => auth.displayName || '未登录')
const avatarText = computed(() => (auth.displayName ? auth.displayName.slice(0, 1) : 'A').toUpperCase())
const ROLE_LABEL: Record<string, string> = {
  system: '系统管理员',
  tenant_admin: '租户管理员',
  normal: '普通用户',
}
const roleLabel = computed(() => ROLE_LABEL[auth.role] ?? auth.role ?? '')
const tenantLabel = computed(() => (auth.tenantId ? `租户 ${auth.tenantId}` : ''))
const userSubline = computed(() => [roleLabel.value, tenantLabel.value].filter(Boolean).join(' · '))
const loggingOut = ref(false)
const shellReady = computed(() => !auth.isLoggedIn || auth.menusStatus === 'ready')
const dataStatus = ref<DataStatus | null>(null)
const dataStatusFailed = ref(false)
const shellTasks = ref<AsyncTask[]>([])
const shellTasksFailed = ref(false)
const shellStatusLoading = ref(false)
const themeStripRef = ref<HTMLElement | null>(null)
const themeScrollLeft = ref(0)
const themeScrollClientWidth = ref(1)
const themeScrollWidth = ref(1)
const canReadDataStatus = computed(() => auth.isSystem || auth.permissions.includes('data-status:view'))
const canReadTradeCalendar = computed(() => auth.isSystem || auth.permissions.includes('trade-calendar:view'))
const canReadTasks = computed(() => auth.isSystem || auth.permissions.includes('data-task:manage'))
const { dataMax: latestReadableTradeDate, ensureLoaded: ensureTradeDatesLoaded } = useTradeDates()
let shellBootstrapping = false
let presetOverridesLoaded = false
let shellStatusRequestId = 0
let shellStatusTimer: number | undefined

const numberFormatter = new Intl.NumberFormat('zh-CN')
const latestTradeDateText = computed(() =>
  formatDateOnly(dataStatus.value?.latest_trade_date ?? latestReadableTradeDate.value))
const qualityIssueCount = computed(() => dataStatus.value?.quality_issues ?? 0)
const qualitySignalText = computed(() => {
  if (dataStatusFailed.value) return '!'
  if (!dataStatus.value || qualityIssueCount.value === 0) return ''
  return formatNumber(qualityIssueCount.value)
})
const marketStatusTone = computed<'success' | 'warning' | 'danger' | 'muted'>(() => {
  if (dataStatusFailed.value) return 'danger'
  if (!dataStatus.value) return 'muted'
  return qualityIssueCount.value > 0 ? 'warning' : 'success'
})
const recentUpdatePreview = computed(() => dataStatus.value?.recent_updates?.slice(0, 3) ?? [])
const activeShellTasks = computed(() =>
  shellTasks.value.filter((task) => task.status === 'pending' || task.status === 'running'))
const failedShellTasks = computed(() =>
  shellTasks.value.filter((task) => task.status === 'failed' || task.status === 'interrupted'))
const taskTone = computed<'success' | 'warning' | 'danger' | 'muted'>(() => {
  if (shellTasksFailed.value) return 'danger'
  if (activeShellTasks.value.length > 0) return 'warning'
  if (failedShellTasks.value.length > 0) return 'danger'
  if (shellTasks.value.length > 0) return 'success'
  return 'muted'
})
const taskSignalText = computed(() => {
  if (shellTasksFailed.value) return '!'
  if (activeShellTasks.value.length > 0) return formatNumber(activeShellTasks.value.length)
  if (failedShellTasks.value.length > 0) return formatNumber(failedShellTasks.value.length)
  return ''
})
const activePresetIndex = computed(() =>
  Math.max(0, presetOptions.value.findIndex((option) => option.value === activePresetKey.value)))
const themeOptionsWithSwatches = computed(() =>
  presetOptions.value.map((option) => ({
    ...option,
    swatches: themeSwatchesFor(option.value),
  })),
)
const themeScrollThumbWidth = computed(() => {
  if (themeScrollWidth.value <= themeScrollClientWidth.value) return 100
  return Math.max(24, (themeScrollClientWidth.value / themeScrollWidth.value) * 100)
})
const themeScrollThumbLeft = computed(() => {
  const maxScroll = themeScrollWidth.value - themeScrollClientWidth.value
  if (maxScroll <= 0) return 0
  return (themeScrollLeft.value / maxScroll) * (100 - themeScrollThumbWidth.value)
})

function formatNumber(value: number | null | undefined): string {
  return typeof value === 'number' ? numberFormatter.format(value) : '—'
}

function formatShortTime(value: string | null | undefined): string {
  if (!value) return '—'
  return value.slice(0, 16).replace('T', ' ')
}

function formatDateOnly(value: string | null | undefined): string {
  if (!value) return '未同步'
  return value.slice(0, 10)
}

function taskTypeLabel(task: AsyncTask): string {
  return TASK_LABEL[task.task_type] ?? task.task_type
}

function taskStatusLabel(status: TaskStatus): string {
  return STATUS_LABEL[status] ?? status
}

function goTo(path: string) {
  void router.push(path)
}

function selectPreset(key: LayoutPresetKey) {
  setLayoutPreset(key)
}

function syncThemeScroll() {
  const el = themeStripRef.value
  if (!el) return
  themeScrollLeft.value = el.scrollLeft
  themeScrollClientWidth.value = Math.max(1, el.clientWidth)
  themeScrollWidth.value = Math.max(1, el.scrollWidth)
}

function themeSwatchesFor(key: LayoutPresetKey) {
  const tokens = effectivePresetTokens(key, isDark.value ? 'dark' : 'light')
  return [
    { key: 'primary', value: tokens.primary, weight: 44 },
    { key: 'success', value: tokens.success, weight: 26 },
    { key: 'warning', value: tokens.warning, weight: 18 },
    { key: 'danger', value: tokens.danger, weight: 12 },
  ]
}

function clearShellStatusTimer() {
  if (!shellStatusTimer) return
  window.clearTimeout(shellStatusTimer)
  shellStatusTimer = undefined
}

async function refreshShellStatus() {
  clearShellStatusTimer()
  if (isFullscreen.value || !auth.isLoggedIn || auth.menusStatus !== 'ready') {
    shellStatusRequestId += 1
    shellStatusLoading.value = false
    dataStatus.value = null
    dataStatusFailed.value = false
    shellTasks.value = []
    shellTasksFailed.value = false
    return
  }
  const requestId = ++shellStatusRequestId
  shellStatusLoading.value = true

  const jobs: Promise<void>[] = []
  if (canReadTradeCalendar.value) {
    jobs.push(ensureTradeDatesLoaded().catch(() => undefined))
  }
  if (canReadDataStatus.value) {
    jobs.push(getDataStatus()
      .then((status) => {
        if (requestId !== shellStatusRequestId) return
        dataStatus.value = status
        dataStatusFailed.value = false
      })
      .catch(() => {
        if (requestId !== shellStatusRequestId) return
        dataStatusFailed.value = true
      }))
  } else {
    dataStatus.value = null
    dataStatusFailed.value = false
  }

  if (canReadTasks.value) {
    jobs.push(listTasks({ limit: 6, sort: 'time', order: 'desc' })
      .then((result) => {
        if (requestId !== shellStatusRequestId) return
        shellTasks.value = result.tasks
        shellTasksFailed.value = false
      })
      .catch(() => {
        if (requestId !== shellStatusRequestId) return
        shellTasksFailed.value = true
      }))
  } else {
    shellTasks.value = []
    shellTasksFailed.value = false
  }

  await Promise.all(jobs)
  if (requestId !== shellStatusRequestId) return
  shellStatusLoading.value = false
  if (activeShellTasks.value.length > 0) {
    shellStatusTimer = window.setTimeout(refreshShellStatus, 5000)
  }
}

async function loadPresetOverridesAfterAuth() {
  if (presetOverridesLoaded) return
  const { presets } = await listLayoutPresets()
  const map: Record<string, Record<string, string | number>> = {}
  for (const p of presets) {
    const values = p.config?.values
    if (values && Object.keys(values).length) map[p.key] = values as Record<string, string | number>
  }
  if (Object.keys(map).length) setPresetOverrides(map)
  presetOverridesLoaded = true
}

async function bootstrapAuthenticatedShell() {
  if (shellBootstrapping || isFullscreen.value || !auth.isLoggedIn) return
  shellBootstrapping = true
  try {
    await auth.ensureLoaded()
    await loadPresetOverridesAfterAuth()
  } catch {
    /* 失败(401 等)已由拦截器处理；菜单加载失败由 SideMenu 显错误态 + 重试 */
  } finally {
    shellBootstrapping = false
  }
}

// 非全屏受控页渲染前后都以 /me 为身份事实源；登录页不再发受控布局接口，避免首登旧 401 清新 token。
watch(() => [isFullscreen.value, auth.isLoggedIn, auth.menusStatus], bootstrapAuthenticatedShell, { immediate: true })
watch(
  () => [isFullscreen.value, auth.isLoggedIn, auth.menusStatus, auth.role, auth.permissions.join('|')],
  () => {
    void refreshShellStatus()
  },
  { immediate: true },
)
onUnmounted(clearShellStatusTimer)
watch(appearanceDrawerVisible, async (visible) => {
  if (!visible) return
  await nextTick()
  syncThemeScroll()
})

async function onLogout() {
  loggingOut.value = true
  try {
    await auth.logout()
  } finally {
    loggingOut.value = false
    userDrawerVisible.value = false
    router.push('/login')
  }
}
</script>

<template>
  <router-view v-if="isFullscreen" :key="route.path" />
  <el-container v-else class="app">
    <el-header class="topbar">
      <div class="topbar-brand">
        <BrandMark variant="shell" :tone="isDark ? 'dark' : 'light'" />
      </div>
      <div class="topbar-slot" />
      <div class="topbar-actions">
        <el-popover
          v-if="canReadDataStatus"
          trigger="click"
          placement="bottom-end"
          :width="330"
          popper-class="topbar-popover"
        >
          <template #reference>
            <button
              class="topbar-action topbar-action--wide"
              :class="`is-${marketStatusTone}`"
              type="button"
              aria-label="交易数据状态"
            >
              <el-icon><Calendar /></el-icon>
              <span class="topbar-action-label">交易日 {{ latestTradeDateText }}</span>
              <span v-if="qualitySignalText" class="topbar-action-value">{{ qualitySignalText }}</span>
            </button>
          </template>

          <div class="topbar-panel">
            <header class="topbar-panel-head">
              <div>
                <div class="topbar-panel-title">交易数据状态</div>
                <div class="topbar-panel-sub">EOD 数据、质量与最近更新</div>
              </div>
              <button class="topbar-refresh" type="button" aria-label="刷新状态" @click="refreshShellStatus">
                <el-icon><Refresh /></el-icon>
              </button>
            </header>

            <div class="topbar-metrics">
              <div class="topbar-metric">
                <span>交易日</span>
                <strong>{{ latestTradeDateText }}</strong>
              </div>
              <div class="topbar-metric">
                <span>股票数</span>
                <strong>{{ formatNumber(dataStatus?.distinct_codes) }}</strong>
              </div>
              <div class="topbar-metric">
                <span>行情行数</span>
                <strong>{{ formatNumber(dataStatus?.bar_rows) }}</strong>
              </div>
              <div class="topbar-metric">
                <span>活跃问题</span>
                <strong>{{ formatNumber(dataStatus?.quality_issues) }}</strong>
              </div>
            </div>

            <div class="topbar-panel-section">
              <div class="topbar-section-title">最近更新</div>
              <div v-if="recentUpdatePreview.length" class="topbar-update-list">
                <div v-for="log in recentUpdatePreview" :key="`${log.table_name}-${log.updated_at}`" class="topbar-update">
                  <span class="topbar-update-table">{{ log.table_name }}</span>
                  <span class="topbar-update-meta">{{ log.source }} · {{ formatShortTime(log.updated_at) }}</span>
                </div>
              </div>
              <div v-else class="topbar-empty">暂无最近更新</div>
            </div>

            <footer class="topbar-panel-actions">
              <button type="button" @click="goTo('/data/overview')">数据概览</button>
              <button type="button" @click="goTo('/data/quality')">质量检查</button>
            </footer>
          </div>
        </el-popover>
        <button
          v-else
          class="topbar-action topbar-action--wide is-readonly"
          :class="`is-${marketStatusTone}`"
          type="button"
          aria-label="交易日状态（无详情权限）"
          disabled
        >
          <el-icon><Calendar /></el-icon>
          <span class="topbar-action-label">交易日 {{ latestTradeDateText }}</span>
        </button>

        <el-popover
          v-if="canReadTasks"
          trigger="click"
          placement="bottom-end"
          :width="330"
          popper-class="topbar-popover"
        >
          <template #reference>
            <button class="topbar-action" :class="`is-${taskTone}`" type="button" aria-label="任务中心">
              <el-icon><Clock /></el-icon>
              <span class="topbar-action-label">任务中心</span>
              <span v-if="taskSignalText" class="topbar-action-value">{{ taskSignalText }}</span>
            </button>
          </template>

          <div class="topbar-panel">
            <header class="topbar-panel-head">
              <div>
                <div class="topbar-panel-title">任务中心</div>
                <div class="topbar-panel-sub">采集、质检、修复任务概览</div>
              </div>
              <button class="topbar-refresh" type="button" aria-label="刷新任务" @click="refreshShellStatus">
                <el-icon><Refresh /></el-icon>
              </button>
            </header>

            <div v-if="shellTasks.length" class="topbar-task-list">
              <div v-for="task in shellTasks.slice(0, 4)" :key="task.id" class="topbar-task">
                <span class="topbar-task-dot" :class="`is-${task.status}`" />
                <div class="topbar-task-main">
                  <span class="topbar-task-title">{{ taskTypeLabel(task) }}</span>
                  <span class="topbar-task-sub">{{ formatShortTime(task.updated_at) }}</span>
                </div>
                <span class="topbar-task-status">{{ taskStatusLabel(task.status) }}</span>
              </div>
            </div>
            <div v-else class="topbar-empty">暂无任务记录</div>

            <footer class="topbar-panel-actions">
              <button type="button" @click="goTo('/data/ingest')">查看任务</button>
              <button type="button" @click="goTo('/data/schedule')">任务调度</button>
            </footer>
          </div>
        </el-popover>

        <button
          class="topbar-action topbar-action--icon topbar-action--appearance"
          type="button"
          aria-label="外观"
          @click="appearanceDrawerVisible = true"
        >
          <svg
            v-if="isDark"
            class="theme-mode-glyph"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              class="theme-mode-glyph-fill"
              d="M20.2 14.4A7.5 7.5 0 0 1 9.6 3.8 8.6 8.6 0 1 0 20.2 14.4Z"
            />
          </svg>
          <svg
            v-else
            class="theme-mode-glyph"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <circle class="theme-mode-glyph-fill" cx="12" cy="12" r="5.2" />
            <g class="theme-mode-glyph-line">
              <path d="M12 2.8v2.3" />
              <path d="M12 18.9v2.3" />
              <path d="M2.8 12h2.3" />
              <path d="M18.9 12h2.3" />
              <path d="m5.5 5.5 1.6 1.6" />
              <path d="m16.9 16.9 1.6 1.6" />
              <path d="m18.5 5.5-1.6 1.6" />
              <path d="m7.1 16.9-1.6 1.6" />
            </g>
          </svg>
        </button>

        <button class="user-entry" type="button" aria-label="用户中心" @click="userDrawerVisible = true">
          <span class="user-avatar">{{ avatarText }}</span>
        </button>
      </div>
    </el-header>

    <el-container class="app-body">
      <el-aside width="208px" class="aside">
        <SideMenu />
        <div class="aside-foot">
          <div class="foot-note">本地 EOD · 仅供研究</div>
        </div>
      </el-aside>

      <el-container class="workspace">
      <el-main class="main">
        <div v-if="!shellReady" class="shell-gate">
          <template v-if="auth.menusStatus === 'error'">
            <div class="shell-gate-title">权限与菜单加载失败</div>
            <el-button type="primary" @click="auth.retryMe()">重试</el-button>
          </template>
          <template v-else>
            <div class="shell-gate-title">正在加载权限与菜单…</div>
          </template>
        </div>
        <router-view v-else v-slot="{ Component }">
          <component :is="Component" :key="route.path" />
        </router-view>
      </el-main>
      </el-container>
    </el-container>

    <el-drawer v-model="userDrawerVisible" direction="rtl" size="440px" class="user-drawer">
      <div class="drawer-card">
        <header class="drawer-head">
          <span class="drawer-title">用户中心</span>
          <button class="drawer-close" type="button" aria-label="关闭" @click="userDrawerVisible = false">✕</button>
        </header>

        <div class="drawer-body">
          <div class="drawer-user-card">
            <span class="drawer-avatar">{{ avatarText }}</span>
            <div>
              <div class="drawer-user-name">{{ displayName }}</div>
              <div class="drawer-user-sub">{{ userSubline || '登录态' }}</div>
            </div>
          </div>

          <button class="drawer-logout" type="button" :disabled="loggingOut" @click="onLogout">
            {{ loggingOut ? '退出中…' : '退出登录' }}
          </button>
        </div>
      </div>
    </el-drawer>

    <el-drawer v-model="appearanceDrawerVisible" direction="rtl" size="440px" class="appearance-drawer">
      <div class="drawer-card">
        <header class="drawer-head drawer-head--appearance">
          <div class="appearance-head-main">
            <span class="drawer-title">外观</span>
            <button
              class="appearance-mode-icon"
              type="button"
              :aria-label="isDark ? '切换到白天模式' : '切换到夜间模式'"
              @click="toggleTheme"
            >
              <svg
                v-if="isDark"
                class="theme-mode-glyph"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <path
                  class="theme-mode-glyph-fill"
                  d="M20.2 14.4A7.5 7.5 0 0 1 9.6 3.8 8.6 8.6 0 1 0 20.2 14.4Z"
                />
              </svg>
              <svg
                v-else
                class="theme-mode-glyph"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <circle class="theme-mode-glyph-fill" cx="12" cy="12" r="5.2" />
                <g class="theme-mode-glyph-line">
                  <path d="M12 2.8v2.3" />
                  <path d="M12 18.9v2.3" />
                  <path d="M2.8 12h2.3" />
                  <path d="M18.9 12h2.3" />
                  <path d="m5.5 5.5 1.6 1.6" />
                  <path d="m16.9 16.9 1.6 1.6" />
                  <path d="m18.5 5.5-1.6 1.6" />
                  <path d="m7.1 16.9-1.6 1.6" />
                </g>
              </svg>
            </button>
            <span class="appearance-mode-copy">
              <span class="appearance-mode-title">{{ isDark ? '夜间模式' : '白天模式' }}</span>
              <span class="appearance-mode-sub">{{ isDark ? '点击图标切换到白天' : '点击图标切换到夜间' }}</span>
            </span>
          </div>
          <button class="drawer-close" type="button" aria-label="关闭" @click="appearanceDrawerVisible = false">✕</button>
        </header>

        <div class="drawer-body">
          <section class="theme-card">
            <div class="theme-card-head">
              <div>
                <div class="theme-card-title">主题风格</div>
                <div class="theme-card-sub">{{ activePresetIndex + 1 }} / {{ presetOptions.length }}</div>
              </div>
            </div>

            <div class="theme-carousel" aria-label="主题风格滑动选择">
              <div ref="themeStripRef" class="theme-strip" @scroll="syncThemeScroll">
                <button
                  v-for="option in themeOptionsWithSwatches"
                  :key="option.value"
                  class="theme-option"
                  :class="{ 'is-active': option.value === activePresetKey }"
                  type="button"
                  :aria-pressed="option.value === activePresetKey"
                  @click="selectPreset(option.value)"
                >
                  <span
                    class="theme-option-preview"
                    :style="{ backgroundColor: option.swatches[0]?.value }"
                    aria-hidden="true"
                  >
                    <span
                      class="theme-option-slashes"
                      :style="{ backgroundColor: option.swatches[0]?.value }"
                    >
                      <span
                        v-for="swatch in option.swatches"
                        :key="swatch.key"
                        class="theme-option-slash"
                        :style="{
                          backgroundColor: swatch.value,
                          flexGrow: swatch.weight,
                          flexBasis: `${swatch.weight}%`,
                        }"
                      />
                    </span>
                  </span>
                  <span class="theme-option-name">{{ option.label }}</span>
                </button>
              </div>
              <div class="theme-scroll-rail" aria-hidden="true">
                <span
                  class="theme-scroll-thumb"
                  :style="{ width: `${themeScrollThumbWidth}%`, left: `${themeScrollThumbLeft}%` }"
                />
              </div>
            </div>
          </section>
        </div>
      </div>
    </el-drawer>
  </el-container>
</template>

<style scoped>
.app {
  height: 100vh;
  flex-direction: column;
}
.app-body {
  flex: 1 1 auto;
  min-height: 0;
}
.aside {
  background: var(--chrome-bg);
  color: var(--chrome-text);
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--chrome-border);
  min-height: 0;
}
.aside-foot {
  padding: 10px 18px 12px;
  border-top: 1px solid var(--chrome-border);
}
.foot-note {
  font-size: 11px;
  color: var(--chrome-text-muted);
}
.workspace {
  min-width: 0;
  min-height: 0;
  background: var(--el-bg-color-page);
}
.topbar {
  height: 67px;
  padding: 0;
  background:
    radial-gradient(360px 96px at 62px -18px, var(--shell-accent-soft) 0%, transparent 74%),
    radial-gradient(420px 90px at 205px 0, var(--shell-danger-line) 0%, transparent 76%),
    linear-gradient(
      90deg,
      color-mix(in srgb, var(--chrome-bg) 82%, var(--shell-accent) 18%) 0%,
      color-mix(in srgb, var(--chrome-bg) 94%, var(--shell-accent) 6%) 26%,
      var(--chrome-bg) 100%
    );
  border-bottom: 1px solid var(--chrome-border);
  display: flex;
  align-items: center;
  color: var(--chrome-text);
  min-width: 0;
  flex-shrink: 0;
  position: relative;
  overflow: hidden;
}
.topbar::before {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: linear-gradient(90deg, transparent 0%, var(--shell-accent-faint) 12%, transparent 36%);
  opacity: 0.48;
  mask-image: linear-gradient(90deg, #000 0%, #000 24%, transparent 58%);
}
.topbar-brand {
  width: 208px;
  height: 100%;
  padding: 0 12px;
  display: flex;
  align-items: center;
  flex: none;
  position: relative;
  z-index: 1;
}
.topbar-slot {
  flex: 1;
  min-width: 0;
  min-height: 32px;
  align-self: stretch;
  position: relative;
  z-index: 1;
}
.topbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  min-width: 0;
  max-width: 100%;
  padding-right: 24px;
  position: relative;
  z-index: 1;
}
.topbar-action {
  position: relative;
  height: 36px;
  border: 0;
  background: transparent;
  color: var(--chrome-text);
  border-radius: var(--layout-control-radius, 6px);
  padding: 0 9px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  cursor: pointer;
  white-space: nowrap;
  transition: background-color 0.15s ease, color 0.15s ease;
}
.topbar-action:hover {
  background: color-mix(in srgb, var(--chrome-bg-soft-hover) 58%, transparent);
  color: var(--chrome-text-strong);
}
.topbar-action:disabled,
.topbar-action.is-readonly {
  cursor: default;
}
.topbar-action:disabled:hover,
.topbar-action.is-readonly:hover {
  background: transparent;
  color: var(--chrome-text);
}
.topbar-action:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--shell-accent) 62%, transparent);
  outline-offset: 2px;
}
.topbar-action--wide {
  min-width: 0;
}
.topbar-action--icon {
  width: 36px;
  min-width: 36px;
  padding: 0;
}
.topbar-action--appearance {
  border-radius: 50%;
  background: transparent;
  color: var(--chrome-text);
  box-shadow: none;
}
.topbar-action--appearance:hover {
  background: color-mix(in srgb, var(--chrome-bg-soft-hover) 58%, transparent);
  color: var(--chrome-text-strong);
}
.topbar-action-label {
  font-size: 13px;
  font-weight: 600;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}
.topbar-action-value {
  font-size: 12px;
  color: var(--chrome-text-muted);
  font-weight: 600;
}
.topbar-action.is-success > .el-icon {
  color: var(--el-color-success);
}
.topbar-action.is-warning > .el-icon {
  color: var(--el-color-warning);
}
.topbar-action.is-danger > .el-icon {
  color: var(--el-color-danger);
}
.topbar-action.is-success .topbar-action-value {
  color: var(--el-color-success);
}
.topbar-action.is-warning .topbar-action-value {
  color: var(--el-color-warning);
}
.topbar-action.is-danger .topbar-action-value {
  color: var(--el-color-danger);
}
.user-entry {
  border: 0;
  background: transparent;
  color: var(--chrome-text);
  border-radius: 999px;
  width: 38px;
  height: 38px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  cursor: pointer;
  transition: background-color 0.15s ease, color 0.15s ease;
  min-width: 0;
  flex: none;
}
.user-entry:hover {
  background: color-mix(in srgb, var(--chrome-bg-soft-hover) 62%, transparent);
  color: var(--chrome-text-strong);
}
.user-avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: linear-gradient(135deg, #ff6a63, #e11919);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 700;
  flex-shrink: 0;
  box-shadow: 0 6px 16px color-mix(in srgb, var(--el-color-danger) 24%, transparent);
}
:global(.topbar-popover) {
  --el-popover-padding: 0;
  border: 1px solid var(--chrome-border);
  background: var(--el-bg-color-overlay);
  box-shadow: 0 14px 34px color-mix(in srgb, #000 18%, transparent);
}
:global(.topbar-popover.el-popper) {
  color: var(--el-text-color-primary);
}
.topbar-panel {
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.topbar-panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.topbar-panel-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}
.topbar-panel-sub {
  margin-top: 3px;
  font-size: 12px;
  line-height: 18px;
  color: var(--el-text-color-secondary);
}
.topbar-refresh {
  width: 28px;
  height: 28px;
  border: 1px solid var(--el-border-color);
  border-radius: var(--layout-control-radius, 6px);
  background: var(--el-fill-color-extra-light);
  color: var(--el-text-color-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}
.topbar-refresh:hover {
  background: var(--el-fill-color-light);
  border-color: var(--el-border-color-darker);
  color: var(--el-text-color-primary);
}
.topbar-metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.topbar-metric {
  min-width: 0;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--layout-control-radius, 6px);
  background: var(--el-fill-color-extra-light);
  padding: 9px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.topbar-metric span {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.topbar-metric strong {
  font-size: 14px;
  line-height: 20px;
  color: var(--el-text-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.topbar-panel-section {
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.topbar-section-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--el-text-color-regular);
}
.topbar-update-list,
.topbar-task-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.topbar-update,
.topbar-task {
  min-height: 34px;
  display: flex;
  align-items: center;
  gap: 9px;
  border-radius: var(--layout-control-radius, 6px);
  padding: 6px 8px;
  background: color-mix(in srgb, var(--el-fill-color-extra-light) 78%, transparent);
}
.topbar-update {
  justify-content: space-between;
}
.topbar-update-table,
.topbar-task-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 650;
  color: var(--el-text-color-primary);
}
.topbar-update-meta,
.topbar-task-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}
.topbar-task-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--el-text-color-placeholder);
  flex: none;
}
.topbar-task-dot.is-done {
  background: var(--el-color-success);
}
.topbar-task-dot.is-running,
.topbar-task-dot.is-pending {
  background: var(--el-color-warning);
}
.topbar-task-dot.is-failed,
.topbar-task-dot.is-interrupted {
  background: var(--el-color-danger);
}
.topbar-task-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.topbar-task-status {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}
.topbar-empty {
  min-height: 42px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px dashed var(--el-border-color);
  border-radius: var(--layout-control-radius, 6px);
  color: var(--el-text-color-placeholder);
  font-size: 12px;
}
.topbar-panel-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 2px;
}
.topbar-panel-actions button {
  height: 30px;
  border: 1px solid var(--el-border-color);
  border-radius: var(--layout-control-radius, 6px);
  background: var(--el-bg-color);
  color: var(--el-text-color-regular);
  padding: 0 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  cursor: pointer;
  font-size: 12px;
  transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}
.topbar-panel-actions button:hover {
  background: var(--el-fill-color-light);
  border-color: var(--el-border-color-darker);
  color: var(--el-text-color-primary);
}
:deep(.user-drawer),
:deep(.appearance-drawer) {
  --el-drawer-bg-color: transparent;
}
:deep(.user-drawer .el-drawer),
:deep(.appearance-drawer .el-drawer) {
  background: transparent;
  box-shadow: none;
}
:deep(.user-drawer .el-drawer__header),
:deep(.appearance-drawer .el-drawer__header) {
  display: none;
  margin: 0;
  padding: 0;
}
:deep(.user-drawer .el-drawer__body),
:deep(.appearance-drawer .el-drawer__body) {
  padding: 14px;
  display: flex;
}
.drawer-card {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--page-settings-bg);
  border: 1px solid var(--page-settings-border);
  border-radius: 16px;
  box-shadow: 0 10px 30px var(--page-settings-shadow);
  overflow: hidden;
}
.drawer-head {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--page-settings-divider);
}
.drawer-head--appearance {
  gap: 12px;
}
.appearance-head-main {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.drawer-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--page-settings-text);
  flex: none;
}
.drawer-close {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--page-settings-text-muted);
  font-size: 14px;
  cursor: pointer;
  transition: background-color .15s ease, color .15s ease;
}
.drawer-close:hover {
  background: var(--page-settings-seg-hover-bg);
  color: var(--page-settings-text);
}
.drawer-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.drawer-user-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px;
  border: 1px solid var(--page-settings-section-border);
  border-radius: 12px;
  background: var(--page-settings-section-bg);
}
.drawer-avatar {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  background: linear-gradient(135deg, #ff6a63, #e11919);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 700;
  flex-shrink: 0;
}
.drawer-user-name {
  font-size: 16px;
  font-weight: 700;
  color: var(--page-settings-text);
}
.drawer-user-sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--page-settings-text-muted);
}
.appearance-mode-icon {
  width: 30px;
  height: 30px;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: var(--page-settings-text);
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  cursor: pointer;
  flex: none;
  box-shadow: none;
  transition: color 0.15s ease, transform 0.15s ease;
}
.appearance-mode-icon:hover {
  background: transparent;
  color: var(--page-settings-text);
  transform: scale(1.04);
}
.theme-mode-glyph {
  width: 24px;
  height: 24px;
  display: block;
}
.theme-mode-glyph-fill {
  fill: #facc15;
  stroke: #111827;
  stroke-width: 1.7;
  stroke-linejoin: round;
}
.theme-mode-glyph-line {
  fill: none;
  stroke: #facc15;
  stroke-width: 1.9;
  stroke-linecap: round;
}
.appearance-mode-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.appearance-mode-title {
  font-size: 13px;
  line-height: 16px;
  font-weight: 700;
  color: var(--page-settings-text);
}
.appearance-mode-sub {
  font-size: 12px;
  line-height: 15px;
  color: var(--page-settings-text-muted);
}
.theme-card {
  border: 1px solid var(--page-settings-section-border);
  background: var(--page-settings-section-bg);
  border-radius: 12px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 11px;
}
.theme-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.theme-card-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--page-settings-text);
}
.theme-card-sub {
  margin-top: 3px;
  font-size: 12px;
  color: var(--page-settings-text-muted);
}
.theme-carousel {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.theme-strip {
  min-width: 0;
  display: flex;
  gap: 10px;
  overflow-x: auto;
  overflow-y: hidden;
  padding: 2px 0 4px;
  scroll-snap-type: x proximity;
  scrollbar-width: none;
}
.theme-strip::-webkit-scrollbar {
  display: none;
  height: 0;
}
.theme-scroll-rail {
  position: relative;
  height: 4px;
  border-radius: 999px;
  background: var(--page-settings-bg);
  overflow: hidden;
}
.theme-scroll-thumb {
  position: absolute;
  top: 0;
  bottom: 0;
  border-radius: inherit;
  background: var(--page-settings-seg-active-border);
  transition: left 0.08s linear, width 0.15s ease;
}
.theme-option {
  flex: 0 0 96px;
  min-width: 96px;
  border: none;
  background: transparent;
  color: var(--page-settings-text-muted);
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  cursor: pointer;
  text-align: center;
  scroll-snap-align: start;
  transition: color 0.15s ease;
}
.theme-option:hover {
  color: var(--page-settings-text);
}
.theme-option.is-active {
  color: var(--page-settings-text);
}
.theme-option-preview {
  height: 44px;
  border: 1px solid var(--page-settings-section-border);
  border-radius: 0;
  background: transparent;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  clip-path: polygon(10px 0, 100% 0, calc(100% - 10px) 100%, 0 100%);
  transition: background-color 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
}
.theme-option:hover .theme-option-preview {
  border-color: var(--page-settings-border);
}
.theme-option.is-active .theme-option-preview {
  border-color: var(--page-settings-accent);
  box-shadow:
    0 0 0 3px color-mix(in srgb, var(--page-settings-accent) 40%, transparent),
    0 8px 18px color-mix(in srgb, var(--page-settings-accent) 18%, transparent);
}
.theme-option-name {
  min-width: 0;
  font-size: 12px;
  line-height: 18px;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.theme-option-slashes {
  width: 138px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0;
  transform: skewX(-24deg);
  margin-left: -16px;
  margin-right: -16px;
}
.theme-option-slash {
  min-width: 0;
  height: 56px;
  border-radius: 0;
  box-shadow: none;
  flex-shrink: 1;
}
.theme-option-slash:nth-child(2) {
  height: 56px;
  transform: none;
}
.theme-option-slash:nth-child(3) {
  height: 56px;
  transform: none;
}
.theme-option-slash:nth-child(4) {
  height: 56px;
  transform: none;
}
/* 退出登录（stage2·T9）：抽屉底部危险操作，红色描边区分常规项 */
.drawer-logout {
  margin-top: auto;
  border: 1px solid var(--el-color-danger);
  background: transparent;
  color: var(--el-color-danger);
  border-radius: 12px;
  padding: 12px 14px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 0.15s ease, color 0.15s ease;
}
.drawer-logout:hover {
  background: var(--el-color-danger);
  color: #fff;
}
.drawer-logout:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.main {
  background: var(--el-bg-color-page);
  padding: 20px 24px;
  overflow: hidden;          /* 禁止整页滚动：超高内容由各页内部成长区自行滚动 */
  display: flex;
  flex-direction: column;
}
/* 路由视图填满内容区高度，作为各页 .v-page 的高度基准 */
.main > * {
  flex: 1 1 auto;
  min-height: 0;
}
.shell-gate {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  color: var(--el-text-color-secondary);
}
.shell-gate-title {
  font-size: 14px;
}

@media (max-width: 720px) {
  .topbar {
    padding: 0;
  }
  .topbar-brand {
    width: 172px;
    padding: 0 10px;
  }
  .topbar-actions {
    padding-right: 10px;
    gap: 6px;
  }
  .topbar-action {
    width: 34px;
    min-width: 34px;
    padding: 0;
  }
  .topbar-action-label,
  .topbar-action-value {
    display: none;
  }
  .user-entry {
    width: 34px;
    height: 34px;
    padding: 0;
  }
  .user-avatar {
    width: 28px;
    height: 28px;
  }
}
</style>
