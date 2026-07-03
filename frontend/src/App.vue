<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useTheme, toggleTheme } from '@/composables/useTheme'
import { useLayoutPreset, type LayoutPresetKey } from '@/layout'
import { useAuthStore } from '@/stores/auth'
import SideMenu from '@/components/SideMenu.vue'

const { isDark } = useTheme()
const { activePresetKey, activePreset, options: presetOptions, setLayoutPreset } = useLayoutPreset()
const userDrawerVisible = ref(false)
// 全屏独立壳（stage2·T7）：登录页等 meta.fullscreen 路由脱离主框架（侧栏/顶栏）单独渲染
const route = useRoute()
const router = useRouter()
const isFullscreen = computed(() => Boolean(route.meta.fullscreen))

// 顶栏用户区（stage2·T9）：身份来自 auth store（登录态从 localStorage 自 hydrate）
const auth = useAuthStore()
const displayName = computed(() => auth.displayName || '未登录')
const avatarText = computed(() => displayName.value.slice(0, 1).toUpperCase())
const ROLE_LABEL: Record<string, string> = {
  system: '系统管理员',
  tenant_admin: '租户管理员',
  normal: '普通用户',
}
const roleLabel = computed(() => ROLE_LABEL[auth.role] ?? auth.role ?? '')
const tenantLabel = computed(() => (auth.tenantId ? `租户 ${auth.tenantId}` : ''))
const userSubline = computed(() => [roleLabel.value, tenantLabel.value].filter(Boolean).join(' · '))
const loggingOut = ref(false)

// 挂载即确保 /me 就绪（刷新身份 + 填充菜单/权限，与路由守卫共用去重）：token 失效由 http 拦截器统一 401→跳登录
onMounted(() => {
  if (!isFullscreen.value && auth.isLoggedIn) {
    auth.ensureLoaded().catch(() => {
      /* 失败(401 等)已由拦截器处理；菜单加载失败由 SideMenu 显错误态 + 重试 */
    })
  }
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
  <router-view v-if="isFullscreen" />
  <el-container v-else class="app">
    <el-aside width="208px" class="aside">
      <div class="brand">
        <span class="brand-logo" aria-hidden="true">
          <svg viewBox="0 0 64 64" width="34" height="34">
            <defs>
              <linearGradient id="brandBg" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stop-color="#ff3d2e" />
                <stop offset="1" stop-color="#e11919" />
              </linearGradient>
            </defs>
            <rect width="64" height="64" rx="15" fill="url(#brandBg)" />
            <text x="32" y="40"
                  fill="#ffffff"
                  font-size="24"
                  font-weight="800"
                  text-anchor="middle"
                  letter-spacing="1"
                  font-family="'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif">复盘</text>
          </svg>
        </span>
        <div class="brand-text">
          <div class="brand-title">复盘啦</div>
        </div>
      </div>
      <SideMenu />
      <div class="aside-foot">
        <div class="foot-note">本地 EOD · 仅供研究</div>
      </div>
    </el-aside>

    <el-container class="workspace">
      <el-header class="topbar">
        <div class="topbar-slot" />
        <div class="topbar-actions">
          <button class="user-entry" type="button" @click="userDrawerVisible = true">
            <span class="user-avatar">{{ avatarText }}</span>
            <span class="user-name">hello，{{ displayName }}！</span>
          </button>
        </div>
      </el-header>

      <el-main class="main">
        <router-view v-slot="{ Component }">
          <component :is="Component" />
        </router-view>
      </el-main>
    </el-container>

    <el-drawer v-model="userDrawerVisible" direction="rtl" size="320px" class="user-drawer">
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

          <button class="drawer-action" type="button" @click="toggleTheme">
            <div>
              <div class="drawer-action-title">主题模式</div>
              <div class="drawer-action-sub">切换白天 / 夜间显示风格</div>
            </div>
            <span class="drawer-action-value">{{ isDark ? '夜间' : '白天' }}</span>
          </button>

          <div class="drawer-section">
            <div class="drawer-section-head">
              <div>
                <div class="drawer-action-title">布局风格</div>
                <div class="drawer-action-sub">{{ activePreset.description }}</div>
              </div>
              <span class="drawer-action-value">{{ activePreset.name }}</span>
            </div>
            <el-select
              class="preset-select"
              :model-value="activePresetKey"
              @update:model-value="(value: LayoutPresetKey) => setLayoutPreset(value)"
            >
              <el-option
                v-for="option in presetOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </div>

          <button class="drawer-logout" type="button" :disabled="loggingOut" @click="onLogout">
            {{ loggingOut ? '退出中…' : '退出登录' }}
          </button>
        </div>
      </div>
    </el-drawer>
  </el-container>
</template>

<style scoped>
.app {
  height: 100vh;
}
.aside {
  background: var(--chrome-bg);
  color: var(--chrome-text);
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--chrome-border);
}
.brand {
  padding: 18px 18px 14px;
  border-bottom: 1px solid var(--chrome-border);
  display: flex;
  align-items: center;
  gap: 11px;
  background: linear-gradient(180deg, color-mix(in srgb, var(--chrome-bg) 88%, white 12%) 0%, var(--chrome-bg) 100%);
}
.brand-logo {
  flex-shrink: 0;
  display: flex;
  filter: drop-shadow(0 2px 6px rgba(217, 38, 38, 0.4));
}
:global(html:not(.dark)) .brand-logo {
  filter: drop-shadow(0 6px 14px rgba(225, 25, 25, 0.18));
}
.brand-text {
  min-width: 0;
}
.brand-title {
  font-size: 22px;
  font-weight: 800;
  color: var(--chrome-text-strong);
  letter-spacing: 0.5px;
  transform: skewX(-10deg);
  transform-origin: left center;
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
  background: var(--el-bg-color-page);
}
.topbar {
  height: 67px;
  padding: 0 24px;
  background: var(--chrome-bg);
  border-bottom: 1px solid var(--chrome-border);
  display: flex;
  align-items: center;
  color: var(--chrome-text);
}
.topbar-slot {
  flex: 1;
  min-width: 0;
  min-height: 32px;
}
.topbar-actions {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}
.user-entry {
  border: 1px solid var(--chrome-border-strong);
  background: var(--chrome-bg-soft);
  color: var(--chrome-text);
  border-radius: 10px;
  height: 40px;
  padding: 0 14px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}
.user-entry:hover {
  background: var(--chrome-bg-soft-hover);
  border-color: var(--chrome-border-hover);
  color: var(--chrome-text-strong);
}
:global(html:not(.dark)) .user-entry {
  box-shadow: 0 6px 18px rgba(148, 163, 184, 0.12);
}
.user-entry {
  padding-right: 16px;
}
.user-avatar {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: linear-gradient(135deg, #ff6a63, #e11919);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
}
.user-name {
  font-size: 13px;
  font-weight: 500;
}
:deep(.user-drawer) {
  --el-drawer-bg-color: transparent;
}
:deep(.user-drawer .el-drawer) {
  background: transparent;
  box-shadow: none;
}
:deep(.user-drawer .el-drawer__header) {
  display: none;
  margin: 0;
  padding: 0;
}
:deep(.user-drawer .el-drawer__body) {
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
.drawer-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--page-settings-text);
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
.drawer-action {
  border: 1px solid var(--page-settings-section-border);
  background: var(--page-settings-section-bg);
  color: var(--page-settings-text);
  border-radius: 12px;
  padding: 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  cursor: pointer;
  text-align: left;
  transition: background-color 0.15s ease, border-color 0.15s ease;
}
.drawer-action:hover {
  background: var(--page-settings-seg-hover-bg);
  border-color: var(--page-settings-border);
}
.drawer-section {
  border: 1px solid var(--page-settings-section-border);
  background: var(--page-settings-section-bg);
  border-radius: 12px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.drawer-section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.drawer-action-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--page-settings-text);
}
.drawer-action-sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--page-settings-text-muted);
}
.drawer-action-value {
  font-size: 13px;
  color: var(--page-settings-text-subtle);
  white-space: nowrap;
}
.preset-select {
  width: 100%;
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
</style>
