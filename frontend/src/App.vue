<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useTheme, toggleTheme } from '@/composables/useTheme'

const { isDark } = useTheme()
const route = useRoute()
const userDrawerVisible = ref(false)
// 子路由（如 /stocks/600000.SH）高亮其父菜单；数据管理高亮到具体子页
const activeMenu = computed(() => {
  if (route.path.startsWith('/config')) return '/config'
  if (route.path.startsWith('/screen')) return '/screen'
  if (route.path.startsWith('/backtest')) return '/backtest'
  if (route.path.startsWith('/stocks')) return '/stocks'
  if (route.path === '/data') return '/data/overview'
  if (route.path.startsWith('/data/')) return route.path
  return '/board'
})
</script>

<template>
  <el-container class="app">
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
      <el-menu :default-active="activeMenu" :default-openeds="['quotes', 'data', 'system']" router class="menu">
        <el-sub-menu index="quotes">
          <template #title>
            <span class="data-parent" @click.stop="$router.push('/stocks')">📈 最新行情</span>
          </template>
          <el-menu-item index="/stocks">个股行情</el-menu-item>
          <el-menu-item index="/board">每日榜单</el-menu-item>
        </el-sub-menu>
        <el-menu-item index="/screen">🧮 策略筛选</el-menu-item>
        <el-menu-item index="/backtest">🧪 策略回测</el-menu-item>
        <el-menu-item index="/training">🎮 盘感训练</el-menu-item>
        <el-sub-menu index="data">
          <template #title>
            <span class="data-parent" @click.stop="$router.push('/data/overview')">🗄️ 数据管理</span>
          </template>
          <el-menu-item index="/data/overview">数据概览</el-menu-item>
          <el-menu-item index="/data/quality">数据质量</el-menu-item>
          <el-menu-item index="/data/ingest">数据采集</el-menu-item>
          <el-menu-item index="/data/schedule">任务调度</el-menu-item>
        </el-sub-menu>
        <el-sub-menu index="system">
          <template #title>
            <span class="data-parent" @click.stop="$router.push('/config')">⚙️ 系统管理</span>
          </template>
          <el-menu-item index="/config">配置管理</el-menu-item>
        </el-sub-menu>
      </el-menu>
      <div class="aside-foot">
        <div class="foot-note">本地 EOD · 仅供研究</div>
      </div>
    </el-aside>

    <el-container class="workspace">
      <el-header class="topbar">
        <div class="topbar-slot" />
        <div class="topbar-actions">
          <button class="user-entry" type="button" @click="userDrawerVisible = true">
            <span class="user-avatar">本</span>
            <span class="user-name">hello，彭帅疯！</span>
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
            <span class="drawer-avatar">彭</span>
            <div>
              <div class="drawer-user-name">彭帅疯</div>
              <div class="drawer-user-sub">本地单用户工作区</div>
            </div>
          </div>

          <button class="drawer-action" type="button" @click="toggleTheme">
            <div>
              <div class="drawer-action-title">主题模式</div>
              <div class="drawer-action-sub">切换白天 / 夜间显示风格</div>
            </div>
            <span class="drawer-action-value">{{ isDark ? '夜间' : '白天' }}</span>
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
.menu {
  flex: 1;
  border-right: none;
  background: transparent;
  padding-top: 8px;
}
.menu :deep(.el-menu-item) {
  color: var(--chrome-text);
}
.menu :deep(.el-menu-item.is-active) {
  background: var(--chrome-active-bg);
  color: var(--chrome-text-strong);
  border-left: 3px solid #409eff;
  font-weight: 600;
}
.menu :deep(.el-menu-item:hover) {
  background: var(--chrome-bg-soft);
}
.menu :deep(.el-sub-menu__title) {
  color: var(--chrome-text);
}
.data-parent {
  display: inline-block;
  width: 100%;
}
.menu :deep(.el-sub-menu__title:hover) {
  background: var(--chrome-bg-soft);
  color: var(--chrome-text-strong);
}
.menu :deep(.el-sub-menu .el-menu) {
  background: var(--chrome-submenu-bg);
}
.menu :deep(.el-sub-menu .el-menu-item) {
  min-width: 0;
  padding-left: 44px !important;
}
:global(html:not(.dark)) .menu :deep(.el-menu-item.is-active) {
  box-shadow: inset 0 0 0 1px rgba(64, 158, 255, 0.12);
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
