<script setup lang="ts">
// 侧边导航（多租户 RBAC stage3·T15）：消费后端数据化菜单 auth.menus（按角色授权 ∩ 可见性双过滤）。
// fail-closed：登录态未就绪显加载中、失败显错误+重试，**不回退静态全量菜单**（避免露越权入口；原 menuConfig.ts 已删）。
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Loading } from '@element-plus/icons-vue'
import SideMenuItem from './SideMenuItem.vue'
import { useAuthStore } from '@/stores/auth'
import { activeMenuPath, type MenuTreeNode } from '@/utils/permission'

const route = useRoute()
const auth = useAuthStore()

const menus = computed<MenuTreeNode[]>(() => auth.menus)

const activeMenu = computed(() => activeMenuPath(menus.value, route.path))

// 默认只展开当前路由所在的分组链（初次挂载算一次，之后由 el-menu 维护）。
function findOpenTrail(nodes: MenuTreeNode[], target: string, trail: string[] = []): string[] {
  for (const n of nodes) {
    if (n.children?.length) {
      const found = findOpenTrail(n.children, target, [...trail, n.index])
      if (found.length) return found
    } else if (n.index === target) {
      return trail
    }
  }
  return []
}
const defaultOpeneds = computed(() => findOpenTrail(menus.value, activeMenu.value))
</script>

<template>
  <!-- 就绪：按后端菜单渲染 -->
  <el-menu v-if="auth.menusStatus === 'ready' && menus.length" :default-active="activeMenu"
           :default-openeds="defaultOpeneds" unique-opened router class="menu">
    <SideMenuItem v-for="node in menus" :key="node.index" :node="node" />
  </el-menu>

  <!-- 加载中 -->
  <div v-else-if="auth.menusStatus === 'loading' || auth.menusStatus === 'idle'" class="menu-hint">
    <el-icon class="is-loading"><Loading /></el-icon>
    <span>菜单加载中…</span>
  </div>

  <!-- 加载失败（fail-closed：不显示任何菜单，提供重试） -->
  <div v-else class="menu-hint error">
    <span>菜单加载失败</span>
    <el-button size="small" text type="primary" @click="auth.retryMe()">重试</el-button>
  </div>
</template>

<style scoped>
.menu {
  flex: 1;
  border-right: none;
  background: transparent;
  padding: 10px 10px 8px;
}
.menu-hint {
  flex: 1;
  padding: 24px 18px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--app-space-2);
  color: var(--chrome-text-muted);
  font-size: var(--app-font-size-table);
}
.menu-hint.error {
  color: var(--el-color-danger);
}
.menu :deep(.el-menu-item) {
  color: var(--chrome-text);
  margin: 3px 0;
  border-radius: var(--layout-control-radius);
}
.menu :deep(.el-menu-item.is-active) {
  background: var(--chrome-active-bg);
  color: var(--chrome-text-strong);
  border-left: 0;
  font-weight: var(--app-font-weight-section);
  box-shadow: inset 3px 0 var(--el-color-primary);
}
.menu :deep(.el-menu-item.is-active .menu-icon),
.menu :deep(.el-sub-menu.is-active > .el-sub-menu__title .menu-icon) {
  background: var(--chrome-menu-icon-active-bg);
  border-color: var(--chrome-menu-icon-active-border);
  color: var(--chrome-menu-icon-active-color);
}
.menu :deep(.el-menu-item:hover) {
  background: var(--chrome-bg-soft);
}
.menu :deep(.el-sub-menu__title) {
  color: var(--chrome-text);
  margin: 3px 0;
  border-radius: var(--layout-control-radius);
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
  box-shadow:
    inset 3px 0 var(--el-color-primary),
    inset 0 0 0 1px color-mix(in srgb, var(--el-color-primary) 12%, transparent);
}
</style>
