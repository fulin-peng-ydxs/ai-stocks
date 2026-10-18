<script setup lang="ts">
import {
  APP_BOTTOM_FLOATING_PLACEMENT,
  APP_BOTTOM_FLOATING_POPPER_OPTIONS,
} from '@/utils/floatingPlacement'
import AppScrollArea from '@/components/AppScrollArea.vue'
import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowDownBold } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useAppNavigation } from '@/composables/useAppNavigation'
import { useDisplayScale } from '@/composables/useDisplayScale'
import { navigateWorkspaceMenu } from '@/composables/useWorkspaceTabs'
import MenuIcon from '@/components/MenuIcon.vue'
import {
  firstPathInMenu,
  menuContainsPath,
  type MenuTreeNode,
} from '@/utils/permission'

const props = defineProps<{ level: 'primary' | 'secondary' }>()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const { selectedPrimaryMenuIndex } = useAppNavigation()
const {
  effectivePercent: displayScalePercent,
  geometryRevision: displayGeometryRevision,
} = useDisplayScale()

const menus = computed(() => auth.menus)
const activePrimary = computed(() => menus.value.find((node) => menuContainsPath(node, route.path)))
const selectedPrimary = computed(() =>
  menus.value.find((node) => node.index === selectedPrimaryMenuIndex.value)
  ?? activePrimary.value
  ?? menus.value[0],
)
const secondaryMenus = computed(() => selectedPrimary.value?.children ?? [])

watch(
  () => [route.path, menus.value] as const,
  () => {
    if (activePrimary.value) selectedPrimaryMenuIndex.value = activePrimary.value.index
    else if (!menus.value.some((node) => node.index === selectedPrimaryMenuIndex.value)) {
      selectedPrimaryMenuIndex.value = menus.value[0]?.index ?? ''
    }
  },
  { immediate: true },
)

function choosePrimary(node: MenuTreeNode) {
  selectedPrimaryMenuIndex.value = node.index
  if (!node.children?.length) {
    if (node.index.startsWith('/')) void navigateWorkspaceMenu(router, node.index, menus.value)
    return
  }
  if (!menuContainsPath(node, route.path)) {
    const path = firstPathInMenu(node)
    if (path) void navigateWorkspaceMenu(router, path, menus.value)
  }
}

function chooseLeaf(path: string) {
  void navigateWorkspaceMenu(router, path, menus.value)
}

function descendantLeaves(
  node: MenuTreeNode,
  parentTitle = '',
): Array<{ path: string; title: string; icon?: string | null }> {
  if (!node.children?.length) {
    return node.index.startsWith('/')
      ? [{
        path: node.index,
        title: parentTitle ? `${parentTitle} · ${node.title}` : node.title,
        icon: node.icon,
      }]
      : []
  }
  return node.children.flatMap((child) => descendantLeaves(child, parentTitle || node.title))
}
</script>

<template>
  <AppScrollArea as="nav"
    v-if="auth.menusStatus === 'ready' && (level === 'primary' ? menus.length : secondaryMenus.length)"
    class="top-navigation"
    :class="`is-${level}`"
    :data-display-scale="displayScalePercent"
    :data-display-geometry-revision="displayGeometryRevision"
    :aria-label="level === 'primary' ? '一级导航' : '二级导航'"
  >
    <template v-if="level === 'primary'">
      <button
        v-for="node in menus"
        :key="node.index"
        class="primary-entry app-interaction-target app-interaction-nav"
        :class="{ 'is-active': activePrimary?.index === node.index }"
        type="button"
        @click="choosePrimary(node)"
      >
        <span class="app-interaction-content app-interaction-row">
          <MenuIcon v-if="node.icon" :name="node.icon" class="primary-entry-icon" />
          <span>{{ node.title }}</span>
        </span>
      </button>
    </template>

    <template v-else>
      <span class="secondary-context" aria-hidden="true">{{ selectedPrimary?.title }}</span>
      <template v-for="node in secondaryMenus" :key="node.index">
        <el-dropdown
          v-if="node.children?.length"
          trigger="click"
          :placement="APP_BOTTOM_FLOATING_PLACEMENT"
          popper-class="top-navigation-dropdown"
          @command="chooseLeaf"
          :popper-options="APP_BOTTOM_FLOATING_POPPER_OPTIONS"
        >
          <button
            class="secondary-entry app-nav-context-entry app-interaction-target app-interaction-nav"
            :class="{ 'is-active': menuContainsPath(node, route.path) }"
            type="button"
          >
            <span class="app-interaction-content app-interaction-row">
              <MenuIcon v-if="node.icon" :name="node.icon" class="secondary-entry-icon" />
              {{ node.title }}
              <el-icon><ArrowDownBold /></el-icon>
            </span>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item
                v-for="leaf in descendantLeaves(node)"
                :key="leaf.path"
                :command="leaf.path"
                class="app-interaction-target app-interaction-nav"
                :class="{ 'is-active': route.path === leaf.path || route.path.startsWith(leaf.path + '/') }"
              >
                <span class="app-interaction-content app-interaction-row">
                  <MenuIcon v-if="leaf.icon" :name="leaf.icon" class="dropdown-entry-icon" />
                  {{ leaf.title }}
                </span>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <button
          v-else
          class="secondary-entry app-nav-context-entry app-interaction-target app-interaction-nav"
          :class="{ 'is-active': menuContainsPath(node, route.path) }"
          type="button"
          @click="chooseLeaf(node.index)"
        >
          <span class="app-interaction-content app-interaction-row">
            <MenuIcon v-if="node.icon" :name="node.icon" class="secondary-entry-icon" />
            {{ node.title }}
          </span>
        </button>
      </template>
    </template>
  </AppScrollArea>
</template>

<style scoped>
.top-navigation {
  min-width: 0;
  --app-scroll-display: flex;
  --app-scroll-align: center;
}
.top-navigation.is-primary {
  height: 100%;
  --app-scroll-gap: var(--app-space-1);
  padding: 0 var(--app-space-3) 0 var(--app-space-control-gap);
}
.primary-entry {
  flex: none;
  --app-interaction-content-gap: var(--app-space-2);
  position: relative;
  align-self: stretch;
  min-width: 0;
  padding: var(--app-nav-indicator-size) var(--app-space-3) 0;
  border: 0;
  border-radius: var(--app-nav-item-radius);
  background: transparent;
  color: var(--chrome-text);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--app-space-2);
  font-family: var(--app-nav-font-family);
  font-size: var(--app-nav-font-size);
  line-height: var(--app-nav-line-height);
  font-weight: var(--app-nav-weight-primary);
  white-space: nowrap;
  cursor: pointer;
}
/* 一级保留整栏底部定位线，只有悬停/焦点表面使用紧凑高度。 */
.primary-entry.app-interaction-nav {
  --app-interaction-nav-hover-background: transparent;
  --app-interaction-inset: calc((100% - var(--app-nav-context-entry-height)) / 2) var(--app-space-1);
}
.primary-entry.app-interaction-nav::before {
  background: var(--chrome-bg-soft-hover);
}
.primary-entry::after {
  content: '';
  position: absolute;
  left: var(--app-space-3);
  right: var(--app-space-3);
  bottom: 0;
  height: var(--app-nav-indicator-size);
  border-radius: var(--app-nav-indicator-size) var(--app-nav-indicator-size) 0 0;
  background: var(--shell-accent);
  opacity: 0;
  transform: scaleX(.35);
  transition: opacity var(--app-motion-content) var(--app-motion-ease), transform var(--app-motion-content) var(--app-motion-ease);
}
.primary-entry:hover,
.primary-entry.is-active {
  color: var(--chrome-text-strong);
}
.primary-entry.is-active::after {
  opacity: 1;
  transform: scaleX(1);
}
.primary-entry-icon {
  width: var(--app-nav-icon-badge-size);
  height: var(--app-nav-icon-badge-size);
  flex: 0 0 var(--app-nav-icon-badge-size);
  border: 1px solid transparent;
  border-radius: var(--app-nav-item-radius);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--app-font-size-section-title);
  overflow: hidden;
  transition: var(--app-interaction-color-transition);
}
.primary-entry.is-active .primary-entry-icon {
  border-color: var(--chrome-menu-icon-active-border);
  background: var(--chrome-menu-icon-active-bg);
  color: var(--chrome-menu-icon-active-color);
}
.primary-entry:focus-visible {
  outline: none;
}
.primary-entry.app-interaction-nav:focus-visible::before {
  outline: var(--app-nav-indicator-size) solid var(--shell-accent);
  outline-offset: calc(-1 * var(--app-nav-indicator-size));
  opacity: 1;
}
.top-navigation.is-secondary {
  flex: none;
  height: var(--app-nav-context-bar-height);
  --app-scroll-gap: var(--app-nav-entry-gap);
  padding: 0 var(--app-space-5);
  border-bottom: 1px solid var(--chrome-border);
  background: var(--chrome-context-bar-bg);
  color: var(--chrome-text);
}
.secondary-context {
  flex: none;
  margin-right: var(--app-space-2);
  color: var(--chrome-text-muted);
  font-family: var(--app-nav-font-family);
  font-size: var(--app-nav-meta-font-size);
  line-height: var(--app-nav-meta-line-height);
  font-weight: var(--app-nav-weight-regular);
}
.secondary-context::after {
  content: '';
  display: inline-block;
  width: 1px;
  height: var(--app-nav-meta-font-size);
  margin-left: var(--app-space-3);
  vertical-align: -2px;
  background: var(--chrome-border-strong);
}
.secondary-entry {
  font-family: var(--app-nav-font-family);
  font-size: var(--app-nav-font-size);
  line-height: var(--app-nav-line-height);
  font-weight: var(--app-nav-weight-primary);
  white-space: nowrap;
}
.secondary-entry .el-icon { font-size: var(--app-icon-size-xs); }
.secondary-entry-icon {
  width: var(--app-nav-icon-size);
  height: var(--app-nav-icon-size);
  flex: 0 0 var(--app-nav-icon-size);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--app-nav-icon-size-nested) !important;
  color: var(--chrome-text-muted);
  overflow: hidden;
}
.secondary-entry.is-active {
  font-weight: var(--app-nav-weight-active);
}
.secondary-entry.is-active .secondary-entry-icon {
  color: var(--chrome-menu-icon-active-color);
}
@container app-viewport (max-width: 960px) {
  .top-navigation.is-primary { padding-inline: var(--app-nav-indicator-size); }
  .primary-entry { padding-inline: var(--app-space-2); }
  .primary-entry::after { left: var(--app-space-2); right: var(--app-space-2); }
  .secondary-context { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  .primary-entry, .primary-entry-icon, .primary-entry::after { transition: none; }
}
</style>

<style>
.top-navigation-dropdown {
  /* 下拉项会在指针移入时获得焦点，移出后的遗留焦点不代表选中或悬停。 */
  --el-dropdown-menuItem-hover-fill: transparent;
  --el-dropdown-menuItem-hover-color: var(--chrome-text);
}
.top-navigation-dropdown .el-dropdown-menu__item {
  min-height: var(--app-nav-context-entry-height);
  padding-inline: var(--app-nav-entry-padding-x);
  border-radius: var(--app-nav-item-radius);
  font-family: var(--app-nav-font-family);
  font-size: var(--app-nav-font-size);
  line-height: var(--app-nav-line-height);
  font-weight: var(--app-nav-weight-regular);
  color: var(--chrome-text);
}
.top-navigation-dropdown .el-dropdown-menu__item.is-active {
  --el-dropdown-menuItem-hover-fill: var(--chrome-nav-leaf-active-bg);
  --el-dropdown-menuItem-hover-color: var(--el-color-primary);
  --app-interaction-nav-hover-background: var(--chrome-nav-leaf-active-bg);
  --app-interaction-nav-hover-color: var(--el-color-primary);
  color: var(--el-color-primary);
  background: var(--chrome-nav-leaf-active-bg);
  font-weight: var(--app-nav-weight-active);
}
.top-navigation-dropdown .dropdown-entry-icon {
  width: var(--app-nav-icon-size);
  height: var(--app-nav-icon-size);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--app-nav-icon-size-nested);
}
</style>
