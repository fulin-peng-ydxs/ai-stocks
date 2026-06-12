<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useTheme, toggleTheme } from '@/composables/useTheme'

const { isDark } = useTheme()
const route = useRoute()
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
                <stop offset="0" stop-color="#ff5b5b" />
                <stop offset="1" stop-color="#d92626" />
              </linearGradient>
            </defs>
            <rect width="64" height="64" rx="15" fill="url(#brandBg)" />
            <g fill="#ffffff" opacity="0.95">
              <rect x="12" y="37" width="6" height="13" rx="1.6" />
              <rect x="24" y="29" width="6" height="21" rx="1.6" />
              <rect x="36" y="22" width="6" height="28" rx="1.6" />
            </g>
            <g stroke="#ffffff" stroke-width="2" opacity="0.95" stroke-linecap="round">
              <line x1="15" y1="32" x2="15" y2="37" />
              <line x1="27" y1="24" x2="27" y2="29" />
              <line x1="39" y1="17" x2="39" y2="22" />
            </g>
            <path d="M11 45 L25 35 L34 40 L51 19" fill="none" stroke="#fde047"
                  stroke-width="4" stroke-linecap="round" stroke-linejoin="round" />
            <path d="M42 17 L53 16 L52 27 Z" fill="#fde047" />
          </svg>
        </span>
        <div class="brand-text">
          <div class="brand-title">趋势选股</div>
          <div class="brand-sub">选股 · 打分 · 回测</div>
        </div>
      </div>
      <el-menu :default-active="activeMenu" :default-openeds="['data']" router class="menu">
        <el-menu-item index="/board">📈 每日榜单</el-menu-item>
        <el-menu-item index="/config">⚙️ 配置管理</el-menu-item>
        <el-menu-item index="/screen">🧮 策略筛选</el-menu-item>
        <el-menu-item index="/backtest">🧪 策略回测</el-menu-item>
        <el-menu-item index="/stocks">🔍 个股查询</el-menu-item>
        <el-sub-menu index="data">
          <template #title>🗄️ 数据管理</template>
          <el-menu-item index="/data/overview">数据概览</el-menu-item>
          <el-menu-item index="/data/ingest">数据采集与任务</el-menu-item>
          <el-menu-item index="/data/quality">数据质量</el-menu-item>
          <el-menu-item index="/data/schedule">调度与数据源</el-menu-item>
        </el-sub-menu>
      </el-menu>
      <div class="aside-foot">
        <div class="theme-toggle" @click="toggleTheme">
          <span>{{ isDark ? '🌙 夜间' : '🌞 白天' }}</span>
          <el-switch :model-value="isDark" size="small" inline-prompt />
        </div>
        <div class="foot-note">本地 EOD · 仅供研究</div>
      </div>
    </el-aside>

    <el-main class="main">
      <router-view v-slot="{ Component }">
        <component :is="Component" />
      </router-view>
    </el-main>
  </el-container>
</template>

<style scoped>
.app {
  height: 100vh;
}
.aside {
  background: #1d2331;
  color: #c9d1d9;
  display: flex;
  flex-direction: column;
}
.brand {
  padding: 18px 18px 14px;
  border-bottom: 1px solid #2a3142;
  display: flex;
  align-items: center;
  gap: 11px;
}
.brand-logo {
  flex-shrink: 0;
  display: flex;
  filter: drop-shadow(0 2px 6px rgba(217, 38, 38, 0.4));
}
.brand-text {
  min-width: 0;
}
.brand-title {
  font-size: 19px;
  font-weight: 700;
  color: #fff;
  letter-spacing: 1px;
}
.brand-sub {
  font-size: 12px;
  color: #7d8694;
  margin-top: 3px;
}
.menu {
  flex: 1;
  border-right: none;
  background: transparent;
  padding-top: 8px;
}
.menu :deep(.el-menu-item) {
  color: #c9d1d9;
}
.menu :deep(.el-menu-item.is-active) {
  background: #2b3346;
  color: #fff;
  border-left: 3px solid #409eff;
}
.menu :deep(.el-menu-item:hover) {
  background: #262d3d;
}
.menu :deep(.el-sub-menu__title) {
  color: #c9d1d9;
}
.menu :deep(.el-sub-menu__title:hover) {
  background: #262d3d;
  color: #fff;
}
.menu :deep(.el-sub-menu .el-menu) {
  background: #171c28;
}
.menu :deep(.el-sub-menu .el-menu-item) {
  min-width: 0;
  padding-left: 44px !important;
}
.aside-foot {
  padding: 10px 18px 12px;
  border-top: 1px solid #2a3142;
}
.theme-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  font-size: 13px;
  color: #c9d1d9;
  padding: 4px 0;
}
.theme-toggle:hover {
  color: #fff;
}
.foot-note {
  font-size: 11px;
  color: #5a6371;
  margin-top: 6px;
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
