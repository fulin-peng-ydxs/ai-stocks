<script setup lang="ts">
// 侧边导航（多租户 RBAC stage3·T15）：消费后端数据化菜单 auth.menus（按角色授权 ∩ 可见性双过滤）。
// fail-closed：登录态未就绪显加载中、失败显错误+重试，**不回退静态全量菜单**（避免露越权入口；原 menuConfig.ts 已删）。
import { computed, nextTick, ref, watch } from 'vue'
import type { MenuInstance } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { Loading } from '@element-plus/icons-vue'
import SideMenuItem from './SideMenuItem.vue'
import MenuIcon from './MenuIcon.vue'
import { useAuthStore } from '@/stores/auth'
import { activeMenuPath, findMenuTrail, type MenuTreeNode } from '@/utils/permission'
import { navigateWorkspaceMenu } from '@/composables/useWorkspaceTabs'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const menuRef = ref<MenuInstance>()

const menus = computed<MenuTreeNode[]>(() => auth.menus)

// 只投影展示分区，不改授权树；连续的一级直达页面合为无标题区段。
const sections = computed(() => {
  const result: Array<{ key: string; heading?: MenuTreeNode; items: MenuTreeNode[] }> = []
  for (const node of menus.value) {
    if (node.children?.length) {
      result.push({ key: node.index, heading: node, items: node.children })
    } else {
      const previous = result.at(-1)
      if (previous && !previous.heading) previous.items.push(node)
      else result.push({ key: node.index, items: [node] })
    }
  }
  return result
})

const activeMenu = computed(() => activeMenuPath(menus.value, route.path))
// 复用最长路由归属，让分区标题与详情页、工作标签切换保持同一条激活链。
const activeTrail = computed(() => findMenuTrail(menus.value, route.path))
const activeSectionIndex = computed(() => activeTrail.value[0]?.index)

// 与面包屑共用最长匹配的授权层级。
const defaultOpeneds = computed(() => activeTrail.value
  .slice(1)
  .filter((node) => node.children?.length).map((node) => node.index))

// default-openeds 仅在组件创建时生效；标签切换或详情跳转后要重新露出当前项。
// 只响应页面/授权树变化，不监听手动收展，避免与用户浏览其他分组的操作争抢。
watch([() => route.path, () => auth.menusStatus, menus], async (_, __, onCleanup) => {
  let cancelled = false
  onCleanup(() => { cancelled = true })
  await nextTick()
  const menu = menuRef.value
  if (cancelled || auth.menusStatus !== 'ready' || !menu) return
  // 页面离开某分组后收起它；同页浏览其他分组及查询变化不触发此同步。
  const currentGroups = new Set(defaultOpeneds.value)
  const closeGroup = menu.close
  function closeInactiveGroups(nodes: MenuTreeNode[]) {
    for (const node of nodes) {
      if (!node.children?.length) continue
      if (!currentGroups.has(node.index)) closeGroup(node.index)
      closeInactiveGroups(node.children)
    }
  }
  for (const section of sections.value) closeInactiveGroups(section.items)
  for (const index of defaultOpeneds.value) menu.open(index)
  await nextTick()
  if (cancelled) return
  const activeItem = (menu.$el as HTMLElement).querySelector<HTMLElement>('.el-menu-item.is-active')
  activeItem?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
  // 返回分区首项时连同标题一起露出，避免滚动正好把当前分区的上下文裁掉。
  const section = activeItem?.closest('.menu-section')
  if (section?.querySelector('.side-menu-node') === activeItem) {
    section?.querySelector<HTMLElement>('.section-heading')
      ?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
  }
}, { flush: 'post', immediate: true })

function selectMenu(index: string) {
  if (index.startsWith('/')) void navigateWorkspaceMenu(router, index, menus.value)
}
</script>

<template>
  <!-- 就绪：按后端菜单渲染 -->
  <el-menu v-if="auth.menusStatus === 'ready' && menus.length" ref="menuRef" :default-active="activeMenu"
           :default-openeds="defaultOpeneds" class="menu" aria-label="侧栏导航" @select="selectMenu">
    <el-menu-item-group v-for="section in sections" :key="section.key" class="menu-section"
                        :class="{
                          'is-untitled': !section.heading,
                          'is-current-section': !!section.heading && section.heading.index === activeSectionIndex,
                        }">
      <template v-if="section.heading" #title>
        <span class="menu-label section-heading" role="heading" aria-level="2"
              :aria-current="section.heading.index === activeSectionIndex ? 'location' : undefined">
          <span class="menu-icon" aria-hidden="true">
            <MenuIcon v-if="section.heading.icon" :name="section.heading.icon" />
          </span>
          <span class="menu-text">{{ section.heading.title }}</span>
        </span>
      </template>
      <SideMenuItem v-for="node in section.items" :key="node.index" :node="node" />
    </el-menu-item-group>
  </el-menu>

  <!-- 加载中 -->
  <div v-else-if="auth.menusStatus === 'loading' || auth.menusStatus === 'idle'" class="menu-hint" role="status">
    <el-icon class="is-loading"><Loading /></el-icon>
    <span>菜单加载中…</span>
  </div>

  <div v-else-if="auth.menusStatus === 'ready'" class="menu-hint" role="status">
    <span>暂无可用菜单</span>
  </div>

  <!-- 加载失败（fail-closed：不显示任何菜单，提供重试） -->
  <div v-else class="menu-hint error" role="alert">
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
  --el-menu-base-level-padding: var(--app-nav-entry-padding-x);
  --el-menu-level-padding: var(--app-nav-indent);
  --side-menu-icon-size: var(--app-nav-icon-size);
}
.menu :deep(.menu-section + .menu-section) {
  margin-top: var(--app-space-3);
  padding-top: var(--app-space-3);
  border-top: 1px solid var(--chrome-border);
}
.menu :deep(.menu-section > .el-menu-item-group__title) {
  padding: var(--app-space-1) var(--app-space-2);
  font-family: var(--app-nav-font-family);
  font-size: var(--app-nav-meta-font-size);
  line-height: var(--app-nav-meta-line-height);
  font-weight: var(--app-nav-weight-primary);
  color: var(--chrome-text-muted);
}
.menu :deep(.is-untitled > .el-menu-item-group__title) {
  display: none;
}
.menu :deep(.is-current-section > .el-menu-item-group__title) {
  color: var(--chrome-text-strong);
}
.menu :deep(.is-current-section .section-heading .menu-icon) {
  color: var(--chrome-menu-icon-active-color);
}
.menu :deep(.is-current-section .section-heading::after) {
  content: '';
  flex: 0 0 var(--app-nav-location-dot-size);
  width: var(--app-nav-location-dot-size);
  height: var(--app-nav-location-dot-size);
  margin-left: auto;
  border-radius: 50%;
  background: var(--shell-accent);
}
.menu :deep(.menu-label) {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  flex: 1;
  min-width: 0;
}
.menu :deep(.menu-icon) {
  width: var(--app-nav-icon-size);
  height: var(--side-menu-icon-size);
  flex: 0 0 var(--app-nav-icon-size);
  font-size: var(--side-menu-icon-size);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.menu :deep(.menu-text) {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.menu-hint {
  flex: 1;
  padding: var(--app-space-5) var(--app-space-4);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--app-space-2);
  color: var(--chrome-text-muted);
  font-family: var(--app-nav-font-family);
  font-size: var(--app-nav-meta-font-size);
  line-height: var(--app-nav-meta-line-height);
}
.menu-hint.error {
  color: var(--el-color-danger);
}
.menu :deep(.el-menu-item.side-menu-node),
.menu :deep(.side-menu-node > .el-sub-menu__title) {
  --side-menu-icon-size: var(--app-nav-icon-size-nested);
  height: var(--app-nav-side-nested-height);
  line-height: var(--app-nav-line-height);
  padding-left: calc(var(--app-nav-entry-padding-x) + var(--side-menu-depth) * var(--app-nav-indent)) !important;
  padding-right: var(--app-nav-entry-padding-x);
  margin-block: calc(var(--app-space-1) / 2);
  min-width: 0;
  color: var(--chrome-text-muted);
  font-family: var(--app-nav-font-family);
  font-size: var(--app-nav-font-size);
  font-weight: var(--app-nav-weight-regular);
  border-radius: var(--app-nav-item-radius);
}
.menu :deep(.el-menu-item.is-root-menu-node),
.menu :deep(.is-root-menu-node > .el-sub-menu__title) {
  --side-menu-icon-size: var(--app-nav-icon-size);
  height: var(--app-nav-side-primary-height);
  color: var(--chrome-text);
  font-weight: var(--app-nav-weight-primary);
}
.menu :deep(.el-menu-item.side-menu-node.is-active) {
  --app-interaction-nav-hover-background: var(--chrome-nav-leaf-active-hover-bg);
  --app-interaction-nav-hover-color: var(--el-color-primary);
  background: var(--chrome-nav-leaf-active-bg);
  color: var(--el-color-primary);
  border-left: 0;
  font-weight: var(--app-nav-weight-active);
  box-shadow: none;
}
.menu :deep(.el-sub-menu.is-active > .el-sub-menu__title) {
  color: var(--chrome-text-strong);
  font-weight: var(--app-nav-weight-active);
}
.menu :deep(.el-sub-menu .el-menu) {
  background: transparent;
}
.menu :deep(.el-sub-menu__icon-arrow) {
  position: static;
  flex: none;
  width: var(--app-nav-meta-font-size);
  margin: 0 0 0 var(--app-space-2);
  color: var(--chrome-text-muted);
  font-size: var(--app-nav-meta-font-size);
}
.menu :deep(.menu-icon > .el-icon) {
  width: 100%;
  height: 100%;
  margin: 0;
  font-size: inherit;
}
</style>
