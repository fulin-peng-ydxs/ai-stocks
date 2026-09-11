<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Calendar, Clock, Close, Minus, Plus, Refresh, Select } from '@element-plus/icons-vue'
import { useTheme, type ThemeMode } from '@/composables/useTheme'
import {
  useAppNavigation,
  type NavigationMode,
} from '@/composables/useAppNavigation'
import { migrateLocalPreferencesToRemote } from '@/composables/usePreferenceMigration'
import { syncDrawerPreferences } from '@/composables/useDrawerPreferences'
import {
  DISPLAY_SCALE_MAX,
  DISPLAY_SCALE_MIN,
  useDisplayScale,
  type DisplayScaleMode,
} from '@/composables/useDisplayScale'
import { resetWorkspaceTabs } from '@/composables/useWorkspaceTabs'
import {
  confirmAll,
  installUnsavedChangesBeforeUnload,
} from '@/composables/useUnsavedChangesGuard'
import {
  effectivePresetTokens,
  setRuntimePresetSources,
  useLayoutPreset,
} from '@/layout'
import { listLayoutPresets } from '@/api/layout'
import {
  getDataStatus,
  listTasks,
  STATUS_LABEL,
  taskDisplayLabel,
  type AsyncTask,
  type DataStatus,
  type TaskStatus,
} from '@/api/data'
import { useAuthStore } from '@/stores/auth'
import { useTradeDates } from '@/composables/useTradeDates'
import { useTradeDisciplineSummary } from '@/composables/useTradeDisciplineSummary'
import BrandMark from '@/components/BrandMark.vue'
import SideMenu from '@/components/SideMenu.vue'
import TopNavigation from '@/components/TopNavigation.vue'
import WorkspaceTabs from '@/components/WorkspaceTabs.vue'
import WorkspaceRouteView from '@/components/WorkspaceRouteView.vue'
import AppIconButton from '@/components/AppIconButton.vue'
import AppOverflowTooltipHost from '@/components/AppOverflowTooltipHost.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import TradeDisciplineQuickCard from '@/components/trade-discipline/TradeDisciplineQuickCard.vue'

const { isDark, themeMode, setThemeMode, syncThemePreference } = useTheme()
const { navigationMode, setNavigationMode, syncNavigationPreference } = useAppNavigation()
const {
  mode: displayScaleMode,
  effectivePercent: displayScalePercent,
  setMode: setDisplayScaleMode,
  setCustomPercent: setDisplayScalePercent,
  reset: resetDisplayScale,
  syncPreference: syncDisplayScalePreference,
} = useDisplayScale()
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
const canReadDataStatus = computed(() => auth.isSystem || auth.permissions.includes('data-status:view'))
const canReadTradeCalendar = computed(() => auth.isSystem || auth.permissions.includes('trade-calendar:view'))
const canReadTasks = computed(() => auth.isSystem || auth.permissions.includes('data-task:manage'))
const canViewTradeDisciplineQuickCard = computed(() => auth.isSystem || (
  auth.permissions.includes('trade-discipline:view')
  && auth.permissions.includes('trade-discipline:checkin-view')
))
const canSubmitTradeDisciplineCheckin = computed(
  () => auth.isSystem || auth.permissions.includes('trade-discipline:checkin-submit'),
)
const { dataMax: latestReadableTradeDate, ensureLoaded: ensureTradeDatesLoaded } = useTradeDates()
const {
  summary: tradeDisciplineSummary,
  status: tradeDisciplineSummaryStatus,
  changeVersion: tradeDisciplineChangeVersion,
  latestChange: latestTradeDisciplineChange,
  refreshSummary: refreshTradeDisciplineSummary,
  resetSummary: resetTradeDisciplineSummary,
} = useTradeDisciplineSummary()
let shellBootstrapping = false
let presetOverridesLoaded = false
let shellStatusRequestId = 0
let shellStatusTimer: number | undefined
let removeBeforeUnload: (() => void) | undefined

const numberFormatter = new Intl.NumberFormat('zh-CN')
const latestTradeDateText = computed(() =>
  formatDateOnly(dataStatus.value?.latest_trade_date ?? latestReadableTradeDate.value))
const latestTradeDisciplineDate = computed(
  () => dataStatus.value?.latest_trade_date ?? latestReadableTradeDate.value ?? '',
)
const hasPendingTradeDiscipline = computed(() =>
  canViewTradeDisciplineQuickCard.value
  && tradeDisciplineSummaryStatus.value === 'ready'
  && Boolean(tradeDisciplineSummary.value?.pending),
)
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
const themeOptionsWithSwatches = computed(() =>
  presetOptions.value.map((option) => {
    const tokens = effectivePresetTokens(option.value, isDark.value ? 'dark' : 'light')
    return {
      ...option,
      swatches: [tokens.primary, tokens.success, tokens.warning, tokens.danger],
    }
  }),
)
const navigationOptions: Array<{
  value: NavigationMode
  label: string
  description: string
}> = [
  { value: 'sidebar-tabs', label: '侧栏标签', description: '层级清晰，适合多页面并行研究' },
  { value: 'dual-topbar', label: '双层顶栏', description: '一级在上，二级与子页紧随其下' },
]
const themeModeOptions: Array<{ value: ThemeMode; label: string }> = [
  { value: 'light', label: '白天' },
  { value: 'dark', label: '夜间' },
  { value: 'system', label: '跟随系统' },
]
const displayScaleModeOptions: Array<{ value: DisplayScaleMode; label: string }> = [
  { value: 'auto', label: '自适应' },
  { value: 'custom', label: '自定义' },
]

async function syncGlobalPreferences() {
  if (!auth.isLoggedIn) return
  await migrateLocalPreferencesToRemote()
  await Promise.all([
    syncThemePreference(),
    syncNavigationPreference(),
    syncDrawerPreferences(),
    syncDisplayScalePreference(),
  ])
}

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
  return taskDisplayLabel(task.task_type, task.params)
}

function taskStatusLabel(status: TaskStatus): string {
  return STATUS_LABEL[status] ?? status
}

function goTo(path: string) {
  void router.push(path)
}

function openTradeDiscipline(payload: {
  tab: 'checkin' | 'rules'
  ruleId?: string
  tradeDate?: string
}) {
  userDrawerVisible.value = false
  const query: Record<string, string> = { tab: payload.tab }
  if (payload.ruleId) query.rule_ref = payload.ruleId
  if (payload.tradeDate) query.trade_date = payload.tradeDate
  void router.push({ path: '/trade-discipline', query })
}

// PageSegmented 受控桥：读取当前明暗意图，写入走 setThemeMode（持久化 + 写回账号）。
const themeModeModel = computed<ThemeMode>({
  get: () => themeMode.value,
  set: (mode) => { if (themeMode.value !== mode) setThemeMode(mode) },
})

const displayScaleModeModel = computed<DisplayScaleMode>({
  get: () => displayScaleMode.value,
  set: (value) => setDisplayScaleMode(value),
})

function nudgeDisplayScale(delta: number): void {
  setDisplayScalePercent(displayScalePercent.value + delta)
}

function selectPreset(key: string) {
  setLayoutPreset(key)
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
  setRuntimePresetSources(presets)
  presetOverridesLoaded = true
}

async function bootstrapAuthenticatedShell() {
  if (shellBootstrapping || isFullscreen.value || !auth.isLoggedIn) return
  shellBootstrapping = true
  try {
    await auth.ensureLoaded()
    await migrateLocalPreferencesToRemote()
    await loadPresetOverridesAfterAuth()
  } catch {
    /* 失败(401 等)已由拦截器处理；菜单加载失败由 SideMenu 显错误态 + 重试 */
  } finally {
    shellBootstrapping = false
  }
}

// 非全屏受控页渲染前后都以 /me 为身份事实源；登录页不再发受控布局接口，避免首登旧 401 清新 token。
onMounted(() => {
  removeBeforeUnload = installUnsavedChangesBeforeUnload()
  void syncGlobalPreferences()
})
watch(() => auth.isLoggedIn, (loggedIn) => {
  if (loggedIn) void syncGlobalPreferences()
})
watch(() => [isFullscreen.value, auth.isLoggedIn, auth.menusStatus], bootstrapAuthenticatedShell, { immediate: true })
watch(
  () => [isFullscreen.value, auth.isLoggedIn, auth.menusStatus, auth.role, auth.permissions.join('|')],
  () => {
    void refreshShellStatus()
  },
  { immediate: true },
)
watch(
  () => [
    userDrawerVisible.value,
    canViewTradeDisciplineQuickCard.value,
    latestTradeDisciplineDate.value,
    tradeDisciplineChangeVersion.value,
  ] as const,
  ([visible, permitted, tradeDate, version], previous) => {
    if (!permitted) {
      resetTradeDisciplineSummary()
      return
    }
    const [wasVisible, wasPermitted, previousTradeDate, previousVersion] = previous ?? []
    const shouldLoad = !wasPermitted
      || tradeDate !== previousTradeDate
      || (version !== previousVersion && latestTradeDisciplineChange.value?.source !== 'quick')
      || (visible && !wasVisible)
    if (tradeDate && shouldLoad) void refreshTradeDisciplineSummary(tradeDate)
  },
  { immediate: true },
)
onUnmounted(() => {
  clearShellStatusTimer()
  removeBeforeUnload?.()
})

async function onLogout() {
  if (!(await confirmAll('logout'))) return
  loggingOut.value = true
  try {
    await auth.logout()
  } finally {
    resetWorkspaceTabs()
    loggingOut.value = false
    userDrawerVisible.value = false
    router.push('/login')
  }
}
</script>

<template>
  <router-view v-if="isFullscreen" :key="route.path" />
  <el-container v-else class="app" role="region" aria-label="研究工作台">
    <el-header class="topbar" data-testid="app-topbar-surface">
      <div class="topbar-brand">
        <BrandMark :tone="isDark ? 'dark' : 'light'" />
      </div>
      <div class="topbar-slot">
        <TopNavigation v-if="navigationMode === 'dual-topbar'" level="primary" />
      </div>
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
              class="topbar-status"
              :class="`is-${marketStatusTone}`"
              type="button"
              aria-label="交易数据状态"
            >
              <el-icon><Calendar /></el-icon>
              <span class="topbar-status-copy">
                <span class="topbar-status-label">交易日</span>
                <span class="topbar-status-date">{{ latestTradeDateText }}</span>
              </span>
              <span class="topbar-status-signal" aria-hidden="true">
                <i class="topbar-status-dot" />
                <span v-if="qualitySignalText">{{ qualitySignalText }}</span>
              </span>
            </button>
          </template>

          <div class="topbar-panel">
            <header class="topbar-panel-head">
              <div>
                <div class="topbar-panel-title">交易数据状态</div>
                <div class="topbar-panel-sub">EOD 数据、质量与最近更新</div>
              </div>
              <AppIconButton
                label="刷新交易数据状态"
                size="sm"
                variant="soft"
                :loading="shellStatusLoading"
                @click="refreshShellStatus"
              >
                <el-icon><Refresh /></el-icon>
              </AppIconButton>
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
              <el-button size="small" plain @click="goTo('/data/overview')">数据概览</el-button>
              <el-button size="small" plain @click="goTo('/data/quality')">质量检查</el-button>
            </footer>
          </div>
        </el-popover>
        <div
          v-else
          class="topbar-status is-readonly"
          :class="`is-${marketStatusTone}`"
          role="status"
          aria-label="交易日状态（无详情权限）"
        >
          <el-icon><Calendar /></el-icon>
          <span class="topbar-status-copy">
            <span class="topbar-status-label">交易日</span>
            <span class="topbar-status-date">{{ latestTradeDateText }}</span>
          </span>
          <span class="topbar-status-signal" aria-hidden="true">
            <i class="topbar-status-dot" />
            <span v-if="qualitySignalText">{{ qualitySignalText }}</span>
          </span>
        </div>

        <el-popover
          v-if="canReadTasks"
          trigger="click"
          placement="bottom-end"
          :width="330"
          popper-class="topbar-popover"
        >
          <template #reference>
            <AppIconButton
              class="topbar-tool"
              :class="`is-${taskTone}`"
              label="任务中心"
            >
              <el-icon><Clock /></el-icon>
              <template #badge>
                <span
                  class="topbar-tool-signal"
                  :class="[{ 'is-dot': !taskSignalText }, `is-${taskTone}`]"
                  aria-hidden="true"
                >{{ taskSignalText }}</span>
              </template>
            </AppIconButton>
          </template>

          <div class="topbar-panel">
            <header class="topbar-panel-head">
              <div>
                <div class="topbar-panel-title">任务中心</div>
                <div class="topbar-panel-sub">采集、质检、修复任务概览</div>
              </div>
              <AppIconButton
                label="刷新任务"
                size="sm"
                variant="soft"
                :loading="shellStatusLoading"
                @click="refreshShellStatus"
              >
                <el-icon><Refresh /></el-icon>
              </AppIconButton>
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
              <el-button size="small" plain @click="goTo('/data/ingest')">查看任务</el-button>
              <el-button size="small" plain @click="goTo('/data/schedule')">任务调度</el-button>
            </footer>
          </div>
        </el-popover>

        <AppIconButton
          class="topbar-tool topbar-tool--appearance"
          label="视觉环境"
          @click="appearanceDrawerVisible = true"
        >
          <svg class="skin-glyph" viewBox="0 0 24 24" aria-hidden="true">
            <path
              class="skin-glyph-body"
              d="M8.1 4.3 4.6 6.2 3.3 10.7l3.1 1.1.9-2.1v9.9h9.4V9.7l.9 2.1 3.1-1.1-1.3-4.5-3.5-1.9-2.1 1.5a3.2 3.2 0 0 1-3.6 0L8.1 4.3Z"
            />
            <path class="skin-glyph-neck" d="M9.4 4.9a3.5 3.5 0 0 0 5.2 0" />
            <circle class="skin-glyph-swatch skin-glyph-swatch--primary" cx="9.2" cy="13.5" r="1.35" />
            <circle class="skin-glyph-swatch skin-glyph-swatch--success" cx="12" cy="13.5" r="1.35" />
            <circle class="skin-glyph-swatch skin-glyph-swatch--warning" cx="14.8" cy="13.5" r="1.35" />
          </svg>
        </AppIconButton>

        <AppIconButton class="user-entry" label="用户中心" @click="userDrawerVisible = true">
          <span class="user-avatar">{{ avatarText }}</span>
          <span v-if="hasPendingTradeDiscipline" class="user-discipline-dot" aria-label="有待打卡交易纪律" />
        </AppIconButton>
      </div>
    </el-header>

    <TopNavigation v-if="navigationMode === 'dual-topbar'" level="secondary" />

    <el-container class="app-body">
      <el-aside
        v-if="navigationMode === 'sidebar-tabs'"
        width="208px"
        class="aside"
        data-testid="app-sidebar-surface"
      >
        <SideMenu />
        <div class="aside-foot">
          <div class="foot-note">本地 EOD · 仅供研究</div>
        </div>
      </el-aside>

      <el-container class="workspace" data-testid="app-workspace-surface">
        <WorkspaceTabs v-if="navigationMode === 'sidebar-tabs' && shellReady" />
        <el-main class="main" data-testid="app-main-surface">
          <div v-if="!shellReady" class="shell-gate">
            <template v-if="auth.menusStatus === 'error'">
              <div class="shell-gate-title">权限与菜单加载失败</div>
              <el-button type="primary" @click="auth.retryMe()">重试</el-button>
            </template>
            <template v-else>
              <div class="shell-gate-title">正在加载权限与菜单…</div>
            </template>
          </div>
          <WorkspaceRouteView v-else />
        </el-main>
      </el-container>
    </el-container>

    <el-drawer v-model="userDrawerVisible" direction="rtl" size="440px" class="user-drawer">
      <div class="drawer-card">
        <header class="drawer-head">
          <span class="drawer-title">用户中心</span>
          <AppIconButton class="drawer-close" label="关闭用户中心" size="sm" @click="userDrawerVisible = false">
            <el-icon><Close /></el-icon>
          </AppIconButton>
        </header>

        <div class="drawer-body">
          <div class="drawer-user-card">
            <span class="drawer-avatar">{{ avatarText }}</span>
            <div>
              <div class="drawer-user-name">{{ displayName }}</div>
              <div class="drawer-user-sub">{{ userSubline || '登录态' }}</div>
            </div>
          </div>

          <TradeDisciplineQuickCard
            v-if="canViewTradeDisciplineQuickCard"
            :can-submit="canSubmitTradeDisciplineCheckin"
            :trade-date="latestTradeDisciplineDate"
            @navigate="openTradeDiscipline"
          />

          <el-button class="drawer-logout" type="danger" plain :loading="loggingOut" @click="onLogout">
            退出登录
          </el-button>
        </div>
      </div>
    </el-drawer>

    <el-drawer v-model="appearanceDrawerVisible" direction="rtl" size="440px" class="appearance-drawer">
      <div class="drawer-card">
        <header class="drawer-head drawer-head--appearance">
          <div>
            <div class="drawer-title">视觉环境</div>
            <div class="drawer-subtitle">调整界面比例、阅读光线与导航方式</div>
          </div>
          <AppIconButton class="drawer-close" label="关闭视觉环境" size="sm" @click="appearanceDrawerVisible = false">
            <el-icon><Close /></el-icon>
          </AppIconButton>
        </header>

        <div class="drawer-body">
          <section class="theme-card">
            <div class="theme-card-head">
              <div>
                <div class="theme-card-title">界面比例</div>
                <div class="theme-card-sub">100% 为原始设计尺寸；自动模式小屏缩小、大屏放大</div>
              </div>
              <output class="display-scale-value" aria-live="polite">{{ displayScalePercent }}%</output>
            </div>
            <PageSegmented
              v-model="displayScaleModeModel"
              aria-label="界面比例模式"
              test-id="appearance-display-scale-mode"
              :options="displayScaleModeOptions"
            />
            <div class="display-scale-control">
              <AppIconButton
                label="缩小界面"
                size="sm"
                :disabled="displayScalePercent <= DISPLAY_SCALE_MIN"
                @click="nudgeDisplayScale(-1)"
              >
                <el-icon><Minus /></el-icon>
              </AppIconButton>
              <el-slider
                class="display-scale-slider"
                :model-value="displayScalePercent"
                :min="DISPLAY_SCALE_MIN"
                :max="DISPLAY_SCALE_MAX"
                :step="1"
                :show-tooltip="false"
                aria-label="调整界面比例"
                data-testid="appearance-display-scale-slider"
                @input="setDisplayScalePercent"
              />
              <AppIconButton
                label="放大界面"
                size="sm"
                :disabled="displayScalePercent >= DISPLAY_SCALE_MAX"
                @click="nudgeDisplayScale(1)"
              >
                <el-icon><Plus /></el-icon>
              </AppIconButton>
            </div>
            <div class="display-scale-foot">
              <span>{{ displayScaleMode === 'auto' ? `已按当前屏幕自动调整为 ${displayScalePercent}%` : '已使用自定义比例' }}</span>
              <el-button link type="primary" @click="resetDisplayScale">恢复100%</el-button>
            </div>
          </section>

          <section class="theme-card">
            <div class="theme-card-head">
              <div>
                <div class="theme-card-title">明暗模式</div>
                <div class="theme-card-sub">跟随系统时随系统浅色/深色自动切换</div>
              </div>
            </div>
            <PageSegmented
              v-model="themeModeModel"
              aria-label="明暗模式"
              test-id="appearance-theme-mode"
              :options="themeModeOptions"
            >
              <template #icon="{ option }">
                <span class="mode-orb" :class="`mode-orb--${option.value}`" aria-hidden="true" />
              </template>
            </PageSegmented>
          </section>

          <section class="theme-card">
            <div class="theme-card-head">
              <div>
                <div class="theme-card-title">视觉预设</div>
                <div class="theme-card-sub">预设改变强调色与布局策略，不改变明暗基础背景</div>
              </div>
            </div>

            <div class="theme-list" aria-label="视觉预设选择">
              <button
                v-for="option in themeOptionsWithSwatches"
                :key="option.value"
                class="theme-option"
                :class="{ 'is-active': option.value === activePresetKey }"
                type="button"
                :aria-pressed="option.value === activePresetKey"
                @click="selectPreset(option.value)"
              >
                <span class="theme-option-signal" aria-hidden="true">
                  <i
                    v-for="(swatch, index) in option.swatches"
                    :key="`${index}-${swatch}`"
                    :class="{ 'is-primary': index === 0 }"
                    :style="{ background: swatch }"
                  />
                </span>
                <span class="theme-option-copy">
                  <strong>{{ option.label }}</strong>
                  <small>{{ option.description }}</small>
                </span>
                <el-icon class="theme-option-check" aria-hidden="true"><Select /></el-icon>
              </button>
            </div>
          </section>

          <section class="theme-card navigation-card">
            <div class="theme-card-head">
              <div>
                <div class="theme-card-title">导航布局</div>
                <div class="theme-card-sub">选择页面之间的组织方式</div>
              </div>
            </div>

            <div class="navigation-list" aria-label="导航布局选择">
              <button
                v-for="option in navigationOptions"
                :key="option.value"
                class="navigation-option"
                :class="{ 'is-active': navigationMode === option.value }"
                type="button"
                :aria-pressed="navigationMode === option.value"
                @click="setNavigationMode(option.value)"
              >
                <span class="navigation-preview" :class="`is-${option.value}`" aria-hidden="true">
                  <i class="nav-preview-head" />
                  <i class="nav-preview-rail" />
                  <i class="nav-preview-sub" />
                  <i class="nav-preview-tabs"><b /><b /></i>
                  <i class="nav-preview-content"><b /><b /></i>
                </span>
                <span class="navigation-option-copy">
                  <strong>{{ option.label }}</strong>
                  <small>{{ option.description }}</small>
                </span>
                <el-icon class="theme-option-check" aria-hidden="true"><Select /></el-icon>
              </button>
            </div>
          </section>

        </div>
      </div>
    </el-drawer>
  </el-container>
  <AppOverflowTooltipHost />
</template>

<style scoped>
.app {
  height: 100%;
  flex-direction: column;
  background: var(--el-bg-color-page);
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
  padding: 12px 18px 14px;
  border-top: 1px solid var(--chrome-border);
}
.foot-note {
  font-size: var(--app-font-size-micro);
  color: var(--chrome-text-muted);
}
.workspace {
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  background: var(--el-bg-color-page);
}
.topbar {
  height: 67px;
  padding: 0;
  background: var(--el-bg-color-page);
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
  content: none;
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
.topbar-slot > * { height: 100%; }
.topbar-actions {
  display: flex;
  align-items: center;
  gap: var(--app-space-control-gap);
  flex-shrink: 0;
  min-width: 0;
  max-width: 100%;
  padding-right: 24px;
  position: relative;
  z-index: 1;
}
.topbar-status {
  height: 32px;
  min-width: 0;
  padding: 0 8px;
  border: 1px solid transparent;
  border-radius: var(--layout-control-radius, 6px);
  background: transparent;
  color: var(--chrome-text);
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-control-gap);
  white-space: nowrap;
}
button.topbar-status {
  cursor: pointer;
  transition: background-color .15s ease, border-color .15s ease, color .15s ease, box-shadow .15s ease;
}
button.topbar-status:hover {
  border-color: color-mix(in srgb, var(--chrome-border-strong) 78%, transparent);
  background: color-mix(in srgb, var(--chrome-bg-soft-hover) 58%, transparent);
  color: var(--chrome-text-strong);
}
button.topbar-status:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--shell-accent) 18%, transparent);
}
.topbar-status.is-readonly {
  cursor: default;
}
.topbar-status > .el-icon {
  font-size: var(--app-font-size-section-title);
  color: var(--chrome-text-muted);
}
.topbar-status-copy {
  min-width: 0;
  display: inline-flex;
  align-items: baseline;
  gap: var(--app-space-control-gap);
}
.topbar-status-label {
  font-size: var(--app-font-size-micro);
  line-height: var(--app-line-height-micro);
  color: var(--chrome-text-muted);
  font-weight: var(--app-font-weight-section);
}
.topbar-status-date {
  font-size: var(--app-font-size-table);
  line-height: var(--app-line-height-caption);
  color: var(--chrome-text);
  font-weight: var(--app-font-weight-section);
  font-variant-numeric: tabular-nums;
  letter-spacing: .01em;
}
.topbar-status-signal {
  min-width: 8px;
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-1);
  color: var(--chrome-text-muted);
  font-size: var(--app-font-size-tiny);
  font-weight: var(--app-font-weight-strong);
  font-variant-numeric: tabular-nums;
}
.topbar-status-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--chrome-text-muted);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--chrome-text-muted) 12%, transparent);
}
.topbar-status.is-success .topbar-status-dot { background: var(--el-color-success); }
.topbar-status.is-warning .topbar-status-dot { background: var(--el-color-warning); }
.topbar-status.is-danger .topbar-status-dot { background: var(--el-color-danger); }
.topbar-status.is-success .topbar-status-signal { color: var(--el-color-success); }
.topbar-status.is-warning .topbar-status-signal { color: var(--el-color-warning); }
.topbar-status.is-danger .topbar-status-signal { color: var(--el-color-danger); }
.topbar-tool {
  color: var(--chrome-text);
}
.topbar-tool:hover:not(:disabled) {
  border-color: transparent;
  background: color-mix(in srgb, var(--chrome-bg-soft-hover) 58%, transparent);
  color: var(--chrome-text-strong);
}
.topbar-tool .el-icon {
  font-size: var(--app-font-size-data);
}
.topbar-tool-signal {
  position: absolute;
  top: 2px;
  right: 1px;
  min-width: 13px;
  height: 13px;
  padding: 0 3px;
  border: 2px solid var(--chrome-bg);
  border-radius: 999px;
  background: var(--chrome-text-muted);
  color: var(--chrome-bg);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--app-font-size-ornament);
  line-height: var(--app-line-height-solid);
  font-weight: var(--app-font-weight-strong);
}
.topbar-tool-signal.is-dot {
  top: 4px;
  right: 3px;
  min-width: 7px;
  width: 7px;
  height: 7px;
  padding: 0;
  border-width: 1px;
}
.topbar-tool-signal.is-success { background: var(--el-color-success); }
.topbar-tool-signal.is-warning { background: var(--el-color-warning); }
.topbar-tool-signal.is-danger { background: var(--el-color-danger); }
.topbar-tool-signal.is-muted { background: var(--chrome-text-muted); }
.skin-glyph {
  width: 18px;
  height: 18px;
  display: block;
}
.skin-glyph-body {
  fill: color-mix(in srgb, currentColor 8%, transparent);
  stroke: currentColor;
  stroke-width: 1.65;
  stroke-linejoin: round;
}
.skin-glyph-neck {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.5;
  stroke-linecap: round;
}
.skin-glyph-swatch {
  stroke: color-mix(in srgb, var(--chrome-bg) 78%, transparent);
  stroke-width: 0.55;
}
.skin-glyph-swatch--primary {
  fill: currentColor;
}
.skin-glyph-swatch--success {
  fill: currentColor;
}
.skin-glyph-swatch--warning {
  fill: currentColor;
}
.user-entry {
  color: var(--chrome-text);
  border-radius: 50%;
  position: relative;
}
.user-entry:hover:not(:disabled) {
  border-color: transparent;
  background: color-mix(in srgb, var(--chrome-bg-soft-hover) 62%, transparent);
  color: var(--chrome-text-strong);
}
.user-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: linear-gradient(135deg, color-mix(in srgb, var(--shell-accent) 72%, white 28%), var(--shell-accent));
  color: var(--shell-control-mark);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-strong);
  flex-shrink: 0;
  box-shadow: 0 3px 9px color-mix(in srgb, var(--shell-accent) 18%, transparent);
}
.user-discipline-dot {
  position: absolute;
  top: 3px;
  right: 2px;
  width: 8px;
  height: 8px;
  border: 2px solid var(--chrome-bg);
  border-radius: 50%;
  background: var(--el-color-warning);
  box-sizing: content-box;
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
  gap: var(--app-space-3);
}
.topbar-panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-3);
}
.topbar-panel-title {
  font-size: var(--app-font-size-body);
  font-weight: var(--app-font-weight-strong);
  color: var(--el-text-color-primary);
}
.topbar-panel-sub {
  margin-top: 3px;
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-caption);
  color: var(--el-text-color-secondary);
}
.topbar-metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--app-space-2);
}
.topbar-metric {
  min-width: 0;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--layout-control-radius, 6px);
  background: var(--el-fill-color-extra-light);
  padding: 9px 10px;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
}
.topbar-metric span {
  font-size: var(--app-font-size-caption);
  color: var(--el-text-color-secondary);
}
.topbar-metric strong {
  font-size: var(--app-font-size-body);
  line-height: var(--app-line-height-table);
  color: var(--el-text-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.topbar-panel-section {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}
.topbar-section-title {
  font-size: var(--app-font-size-caption);
  font-weight: var(--app-font-weight-strong);
  color: var(--el-text-color-regular);
}
.topbar-update-list,
.topbar-task-list {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-control-gap);
}
.topbar-update,
.topbar-task {
  min-height: 34px;
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
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
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-section);
  color: var(--el-text-color-primary);
}
.topbar-update-meta,
.topbar-task-sub {
  font-size: var(--app-font-size-caption);
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
  font-size: var(--app-font-size-caption);
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
  font-size: var(--app-font-size-caption);
}
.topbar-panel-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--app-space-2);
  padding-top: 2px;
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
  gap: var(--app-space-3);
}
.drawer-title {
  font-size: var(--app-font-size-section-title);
  font-weight: var(--app-font-weight-strong);
  color: var(--page-settings-text);
  flex: none;
}
.drawer-subtitle {
  margin-top: 3px;
  color: var(--page-settings-text-muted);
  font-size: var(--app-font-size-caption);
}
.drawer-close {
  color: var(--page-settings-text-muted);
}
.drawer-close:hover:not(:disabled) {
  border-color: transparent;
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
  gap: var(--app-space-3);
}
.drawer-user-card {
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
  padding: 14px;
  border: 1px solid var(--page-settings-section-border);
  border-radius: 12px;
  background: var(--page-settings-section-bg);
}
.drawer-avatar {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  background: linear-gradient(135deg, color-mix(in srgb, var(--shell-accent) 72%, white 28%), var(--shell-accent));
  color: var(--shell-control-mark);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--app-font-size-title-md);
  font-weight: var(--app-font-weight-strong);
  flex-shrink: 0;
}
.drawer-user-name {
  font-size: var(--app-font-size-data);
  font-weight: var(--app-font-weight-strong);
  color: var(--page-settings-text);
}
.drawer-user-sub {
  margin-top: 4px;
  font-size: var(--app-font-size-caption);
  color: var(--page-settings-text-muted);
}
/* 明暗模式分段控件的内联状态图形：日=冷白亮蓝、夜=深蓝、系统=半明半暗（DESIGN.md §39）。 */
.mode-orb {
  width: 16px;
  height: 16px;
  flex: none;
  border-radius: 50%;
  border: 1px solid var(--page-settings-border);
  box-shadow: inset 0 0 0 3px color-mix(in srgb, var(--page-settings-bg) 58%, transparent);
}
.mode-orb--light { background: radial-gradient(circle at 38% 35%, #ffffff 0 20%, #9ec5ff 22% 48%, #3b82f6 51% 100%); }
.mode-orb--dark { background: radial-gradient(circle at 60% 38%, #dbeafe 0 16%, #4b7bbd 18% 40%, #172554 43% 100%); }
.mode-orb--system { background: linear-gradient(115deg, #3b82f6 0 50%, #172554 50% 100%); }
.theme-card {
  border: 0;
  background: transparent;
  border-radius: 0;
  padding: 4px 0 0;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
  box-shadow: none;
}
.theme-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-3);
}
.theme-card-title {
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-strong);
  color: var(--page-settings-text);
}
.theme-card-sub {
  margin-top: 1px;
  font-size: var(--app-font-size-caption);
  color: var(--page-settings-text-muted);
}
.display-scale-value {
  flex: none;
  color: var(--page-settings-accent);
  font-family: var(--app-font-family-mono);
  font-size: var(--app-font-size-data);
  font-weight: var(--app-font-weight-strong);
  line-height: var(--app-line-height-data);
  font-variant-numeric: tabular-nums;
}
.display-scale-control {
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
}
.display-scale-slider {
  flex: 1 1 auto;
  min-width: 0;
}
.display-scale-foot {
  min-height: var(--app-control-height-sm);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-3);
  color: var(--page-settings-text-muted);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-caption);
}
.display-scale-foot .el-button {
  flex: none;
}
.theme-list {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}
.theme-option {
  width: 100%;
  min-height: 76px;
  padding: 10px 11px;
  border: 1px solid var(--page-settings-section-border);
  border-radius: 12px;
  background: color-mix(in srgb, var(--page-settings-section-bg) 58%, transparent);
  color: var(--page-settings-text-muted);
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr) 20px;
  align-items: center;
  gap: var(--app-space-3);
  text-align: left;
  cursor: pointer;
  transition: border-color .18s ease, background-color .18s ease, transform .18s ease;
}
.theme-option:hover {
  border-color: var(--page-settings-border);
  transform: translateY(-1px);
}
.theme-option.is-active {
  border-color: color-mix(in srgb, var(--page-settings-accent) 62%, var(--page-settings-border));
  background: color-mix(in srgb, var(--page-settings-accent) 7%, var(--page-settings-bg));
}
.theme-option-signal {
  height: 44px;
  padding: 8px;
  border: 1px solid var(--page-settings-section-border);
  border-radius: 8px;
  background: var(--page-settings-bg);
  display: grid;
  grid-template-columns: 2fr 1fr 1fr 1fr;
  align-items: end;
  gap: var(--app-space-1);
}
.theme-option-signal i {
  height: 11px;
  border-radius: 3px;
  opacity: .86;
}
.theme-option-signal i.is-primary {
  height: 26px;
  opacity: 1;
}
.theme-option-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
}
.theme-option-copy strong {
  color: var(--page-settings-text);
  font-size: var(--app-font-size-table);
}
.theme-option-copy small {
  color: var(--page-settings-text-muted);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-caption);
}
.navigation-card {
  padding-top: 2px;
}
.navigation-list {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--app-space-2);
}
.navigation-option {
  position: relative;
  min-width: 0;
  min-height: 142px;
  padding: 9px;
  border: 1px solid var(--page-settings-section-border);
  border-radius: 13px;
  background: color-mix(in srgb, var(--page-settings-section-bg) 58%, transparent);
  color: var(--page-settings-text-muted);
  display: grid;
  grid-template-columns: minmax(0, 1fr) 20px;
  grid-template-rows: 76px auto;
  gap: var(--app-space-2) var(--app-space-control-gap);
  text-align: left;
  cursor: pointer;
  transition: color .18s ease, border-color .18s ease, background-color .18s ease, transform .18s ease;
}
.navigation-option:hover {
  color: var(--page-settings-text);
  border-color: var(--page-settings-border);
  transform: translateY(-1px);
}
.navigation-option.is-active {
  color: var(--page-settings-text);
  border-color: color-mix(in srgb, var(--page-settings-accent) 62%, var(--page-settings-border));
  background: color-mix(in srgb, var(--page-settings-accent) 7%, var(--page-settings-bg));
  box-shadow: 0 8px 22px color-mix(in srgb, var(--page-settings-shadow) 38%, transparent);
}
.navigation-preview {
  position: relative;
  grid-column: 1 / -1;
  width: 100%;
  height: 76px;
  overflow: hidden;
  border: 1px solid var(--page-settings-section-border);
  border-radius: 8px;
  background: color-mix(in srgb, var(--page-settings-bg) 84%, var(--page-settings-section-bg));
}
.nav-preview-head,
.nav-preview-rail,
.nav-preview-sub,
.nav-preview-tabs,
.nav-preview-content {
  position: absolute;
  display: block;
}
.nav-preview-head {
  inset: 0 0 auto;
  height: 15px;
  border-bottom: 1px solid var(--page-settings-section-border);
  background: color-mix(in srgb, var(--page-settings-section-bg) 80%, transparent);
}
.nav-preview-head::before {
  content: '';
  position: absolute;
  left: 7px;
  top: 5px;
  width: 19px;
  height: 4px;
  border-radius: 3px;
  background: var(--page-settings-accent);
  opacity: .78;
}
.nav-preview-rail {
  left: 0;
  top: 15px;
  bottom: 0;
  width: 29px;
  border-right: 1px solid var(--page-settings-section-border);
  background: color-mix(in srgb, var(--page-settings-section-bg) 74%, transparent);
}
.nav-preview-rail::before,
.nav-preview-rail::after {
  content: '';
  position: absolute;
  left: 6px;
  width: 16px;
  height: 3px;
  border-radius: 2px;
  background: var(--page-settings-text-muted);
  opacity: .44;
}
.nav-preview-rail::before { top: 12px; }
.nav-preview-rail::after { top: 23px; }
.nav-preview-sub { display: none; }
.nav-preview-tabs {
  left: 29px;
  right: 0;
  top: 15px;
  height: 13px;
  padding-left: 7px;
  border-bottom: 1px solid var(--page-settings-section-border);
}
.nav-preview-tabs b {
  display: inline-block;
  width: 24px;
  height: 5px;
  margin: 4px 3px 0 0;
  border-radius: 3px;
  background: var(--page-settings-text-muted);
  opacity: .3;
}
.nav-preview-tabs b:first-child { background: var(--page-settings-accent); opacity: .78; }
.nav-preview-content {
  left: 39px;
  right: 9px;
  top: 37px;
  bottom: 9px;
  padding: 7px;
  border: 1px solid var(--page-settings-section-border);
  border-radius: 5px;
}
.nav-preview-content b {
  display: block;
  width: 65%;
  height: 3px;
  margin-bottom: 5px;
  border-radius: 2px;
  background: var(--page-settings-text-muted);
  opacity: .28;
}
.nav-preview-content b:first-child { width: 42%; background: var(--page-settings-accent); opacity: .68; }
.navigation-preview.is-dual-topbar .nav-preview-head::after {
  content: '';
  position: absolute;
  left: 36px;
  right: 8px;
  top: 5px;
  height: 4px;
  border-radius: 3px;
  background: repeating-linear-gradient(90deg, var(--page-settings-text-muted) 0 18px, transparent 18px 26px);
  opacity: .34;
}
.navigation-preview.is-dual-topbar .nav-preview-rail,
.navigation-preview.is-dual-topbar .nav-preview-tabs { display: none; }
.navigation-preview.is-dual-topbar .nav-preview-sub {
  display: block;
  left: 0;
  right: 0;
  top: 15px;
  height: 14px;
  border-bottom: 1px solid var(--page-settings-section-border);
  background: color-mix(in srgb, var(--page-settings-section-bg) 54%, transparent);
}
.navigation-preview.is-dual-topbar .nav-preview-sub::before {
  content: '';
  position: absolute;
  left: 8px;
  top: 5px;
  width: 58px;
  height: 4px;
  border-radius: 3px;
  background: repeating-linear-gradient(90deg, var(--page-settings-accent) 0 20px, transparent 20px 27px);
  opacity: .7;
}
.navigation-preview.is-dual-topbar .nav-preview-content {
  left: 9px;
  top: 38px;
}
.navigation-option-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
}
.navigation-option-copy strong {
  color: var(--page-settings-text);
  font-size: var(--app-font-size-table);
}
.navigation-option-copy small {
  color: var(--page-settings-text-muted);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-caption);
}
.theme-option-check {
  width: 20px;
  height: 20px;
  border: 1px solid var(--page-settings-section-border);
  border-radius: 50%;
  color: transparent;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--app-font-size-micro);
  font-weight: var(--app-font-weight-strong);
}
.theme-option.is-active .theme-option-check,
.navigation-option.is-active .theme-option-check {
  border-color: var(--page-settings-accent);
  background: var(--page-settings-accent);
  color: var(--shell-control-mark);
}
.drawer-logout {
  margin-top: auto;
  width: 100%;
}
.main {
  background: transparent;
  padding: 20px 24px;
  min-height: 0;
  overflow: clip;            /* 外壳不是滚动容器，也禁止 scrollIntoView 产生隐藏 scrollTop */
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
  gap: var(--app-space-3);
  color: var(--el-text-color-secondary);
}
.shell-gate-title {
  font-size: var(--app-font-size-body);
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
    gap: var(--app-space-control-gap);
  }
  .topbar-status {
    width: 32px;
    padding: 0;
    justify-content: center;
  }
  .topbar-status-copy,
  .topbar-status-signal {
    display: none;
  }
}
</style>
