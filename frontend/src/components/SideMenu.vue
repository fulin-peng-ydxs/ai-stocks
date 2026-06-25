<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import SideMenuItem from './SideMenuItem.vue'
import { menuConfig, findOpenPath } from './menuConfig'

const route = useRoute()

// 子路由（如 /stocks/600000.SH）高亮其父菜单；数据管理高亮到具体子页
const activeMenu = computed(() => {
  if (route.path.startsWith('/system/layout')) return route.path
  if (route.path.startsWith('/system/config')) return '/system/config'
  if (route.path.startsWith('/screen')) return '/screen'
  if (route.path.startsWith('/backtest')) return '/backtest'
  if (route.path.startsWith('/stocks')) return '/stocks'
  if (route.path === '/data') return '/data/overview'
  if (route.path.startsWith('/data/')) return route.path
  return '/board'
})

// 默认折叠，只展开当前路由所在的分组（初始挂载时计算一次，之后由 el-menu 维护展开态）
const defaultOpeneds = computed(() => findOpenPath(activeMenu.value))
</script>

<template>
  <!-- el-menu 在持久化外壳内只挂载一次：default-openeds 仅增量追加、不会收起旧组，
       故用 unique-opened（同级只展开一个）实现「默认折叠、只展开当前路由所在组」 -->
  <el-menu :default-active="activeMenu" :default-openeds="defaultOpeneds" unique-opened router class="menu">
    <SideMenuItem v-for="node in menuConfig" :key="node.index" :node="node" />
  </el-menu>
</template>

<style scoped>
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
/* 三级（孙）菜单项再缩进一档，体现 系统管理 → 布局配置 → 工作区 的层级 */
.menu :deep(.el-sub-menu .el-sub-menu .el-menu-item) {
  padding-left: 60px !important;
}
:global(html:not(.dark)) .menu :deep(.el-menu-item.is-active) {
  box-shadow: inset 0 0 0 1px rgba(64, 158, 255, 0.12);
}
</style>
