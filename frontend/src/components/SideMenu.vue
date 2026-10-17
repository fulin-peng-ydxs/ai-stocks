<script setup lang="ts">
// 侧边导航（多租户 RBAC stage3·T15）：消费后端数据化菜单 auth.menus（按角色授权 ∩ 可见性双过滤）。
// fail-closed：登录态未就绪显加载中、失败显错误+重试，**不回退静态全量菜单**（避免露越权入口；原 menuConfig.ts 已删）。
import { computed, nextTick, ref, watch } from 'vue'
import type { MenuInstance } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { Loading } from '@element-plus/icons-vue'
import SideMenuItem from './SideMenuItem.vue'
import { useAuthStore } from '@/stores/auth'
import { activeMenuPath, findMenuTrail, type MenuTreeNode } from '@/utils/permission'
import { resolveWorkspaceMenuPath } from '@/composables/useWorkspaceTabs'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const menuRef = ref<MenuInstance>()

const menus = computed<MenuTreeNode[]>(() => auth.menus)

const activeMenu = computed(() => activeMenuPath(menus.value, route.path))

// 与面包屑共用最长匹配的授权层级。
const defaultOpeneds = computed(() => findMenuTrail(menus.value, route.path)
  .filter((node) => node.children?.length).map((node) => node.index))

// default-openeds 仅在组件创建时生效；标签切换或详情跳转后要重新露出当前项。
// 只响应页面/授权树变化，不监听手动收展，避免与用户浏览其他分组的操作争抢。
watch([() => route.path, () => auth.menusStatus, menus], async () => {
  await nextTick()
  const menu = menuRef.value
  if (auth.menusStatus !== 'ready' || !menu) return
  const trail = defaultOpeneds.value
  const currentGroups = new Set(trail)
  const closeOtherGroups = (nodes: MenuTreeNode[]) => {
    for (const node of nodes) {
      if (!node.children?.length) continue
      if (!currentGroups.has(node.index)) menu.close(node.index)
      closeOtherGroups(node.children)
    }
  }
  closeOtherGroups(menus.value)
  const currentGroup = trail.at(-1)
  if (currentGroup) menu.open(currentGroup)
}, { flush: 'post' })

function selectMenu(index: string) {
  if (index.startsWith('/')) void router.push(resolveWorkspaceMenuPath(index))
}
</script>

<template>
  <!-- 就绪：按后端菜单渲染 -->
  <el-menu v-if="auth.menusStatus === 'ready' && menus.length" ref="menuRef" :default-active="activeMenu"
           :default-openeds="defaultOpeneds" unique-opened class="menu" @select="selectMenu">
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
  padding: 0 var(--app-space-2) var(--app-space-2);
  --el-menu-base-level-padding: 8px;
  --el-menu-level-padding: 12px;
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
.menu :deep(.el-menu-item.side-menu-node),
.menu :deep(.side-menu-node > .el-sub-menu__title) {
  --side-menu-icon-size: 16px;
  height: 36px;
  line-height: var(--app-nav-line-height);
  padding-left: calc(var(--app-space-2) + var(--side-menu-depth) * var(--app-space-3)) !important;
  padding-right: var(--app-space-2);
  margin-block: 2px;
  min-width: 0;
  color: var(--chrome-text-muted);
  font-family: var(--app-nav-font-family);
  font-size: var(--app-nav-font-size);
  font-weight: var(--app-nav-weight-regular);
  border-radius: var(--layout-control-radius);
}
.menu :deep(.el-menu-item.is-root-menu-node),
.menu :deep(.is-root-menu-node > .el-sub-menu__title) {
  --side-menu-icon-size: 18px;
  height: 44px;
  color: var(--chrome-text);
  font-weight: var(--app-nav-weight-primary);
}
.menu :deep(.el-menu-item.side-menu-node.is-active) {
  background: color-mix(in srgb, var(--el-color-primary) 12%, transparent);
  color: var(--el-color-primary);
  border-left: 0;
  font-weight: var(--app-nav-weight-active);
  box-shadow: inset 2px 0 var(--el-color-primary);
}
.menu :deep(.el-sub-menu.is-active > .el-sub-menu__title) {
  color: var(--chrome-text-strong);
  font-weight: var(--app-nav-weight-active);
}
.menu :deep(.el-menu-item:hover) {
  background: var(--chrome-bg-soft);
}
.menu :deep(.el-menu-item.is-active:hover) {
  background: color-mix(in srgb, var(--el-color-primary) 16%, transparent);
}
.menu :deep(.el-sub-menu__title:hover) {
  background: var(--chrome-bg-soft);
  color: var(--chrome-text-strong);
}
.menu :deep(.el-sub-menu .el-menu) {
  background: transparent;
}
.menu :deep(.el-sub-menu__icon-arrow) {
  position: static;
  flex: none;
  width: 12px;
  margin: 0 0 0 var(--app-space-2);
  color: var(--chrome-text-muted);
  font-size: var(--app-font-size-caption);
}
.menu :deep(.menu-icon > .el-icon) {
  width: 100%;
  height: 100%;
  margin: 0;
  font-size: inherit;
}
.menu :deep(.el-menu-item:focus-visible),
.menu :deep(.el-sub-menu__title:focus-visible) {
  outline: 2px solid var(--el-color-primary);
  outline-offset: -2px;
}
</style>
