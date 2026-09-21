<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowDownBold } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useAppNavigation } from '@/composables/useAppNavigation'
import { useDisplayScale } from '@/composables/useDisplayScale'
import { resolveWorkspaceMenuPath } from '@/composables/useWorkspaceTabs'
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
const navigationRenderKey = computed(() => (
  `${props.level}-${displayScalePercent.value}-${displayGeometryRevision.value}`
))

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
    if (node.index.startsWith('/')) void router.push(resolveWorkspaceMenuPath(node.index))
    return
  }
  if (!menuContainsPath(node, route.path)) {
    const path = firstPathInMenu(node)
    if (path) void router.push(resolveWorkspaceMenuPath(path))
  }
}

function chooseLeaf(path: string) {
  void router.push(resolveWorkspaceMenuPath(path))
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
  <nav
    v-if="auth.menusStatus === 'ready' && (level === 'primary' ? menus.length : secondaryMenus.length)"
    :key="navigationRenderKey"
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
        class="primary-entry"
        :class="{ 'is-active': activePrimary?.index === node.index }"
        type="button"
        @click="choosePrimary(node)"
      >
        <MenuIcon v-if="node.icon" :name="node.icon" class="primary-entry-icon" />
        <span>{{ node.title }}</span>
      </button>
    </template>

    <template v-else>
      <span class="secondary-context" aria-hidden="true">{{ selectedPrimary?.title }}</span>
      <template v-for="node in secondaryMenus" :key="node.index">
        <el-dropdown
          v-if="node.children?.length"
          trigger="click"
          placement="bottom-start"
          popper-class="top-navigation-dropdown"
          @command="chooseLeaf"
        >
          <button
            class="secondary-entry"
            :class="{ 'is-active': menuContainsPath(node, route.path) }"
            type="button"
          >
            <MenuIcon v-if="node.icon" :name="node.icon" class="secondary-entry-icon" />
            {{ node.title }}
            <el-icon><ArrowDownBold /></el-icon>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item
                v-for="leaf in descendantLeaves(node)"
                :key="leaf.path"
                :command="leaf.path"
                :class="{ 'is-active': route.path === leaf.path || route.path.startsWith(leaf.path + '/') }"
              >
                <MenuIcon v-if="leaf.icon" :name="leaf.icon" class="dropdown-entry-icon" />
                {{ leaf.title }}
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <button
          v-else
          class="secondary-entry"
          :class="{ 'is-active': menuContainsPath(node, route.path) }"
          type="button"
          @click="chooseLeaf(node.index)"
        >
          <MenuIcon v-if="node.icon" :name="node.icon" class="secondary-entry-icon" />
          {{ node.title }}
        </button>
      </template>
    </template>
  </nav>
</template>

<style scoped>
.top-navigation {
  min-width: 0;
  display: flex;
  align-items: center;
  overflow-x: auto;
  scrollbar-width: none;
}
.top-navigation::-webkit-scrollbar { display: none; }
.top-navigation.is-primary {
  height: 100%;
  gap: var(--app-space-1);
  padding: 0 12px 0 6px;
}
.primary-entry {
  position: relative;
  align-self: stretch;
  min-width: 0;
  padding: 2px 13px 0;
  border: 0;
  background: transparent;
  color: var(--chrome-text-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--app-space-2);
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-section);
  letter-spacing: .02em;
  white-space: nowrap;
  cursor: pointer;
  transition: color .16s ease, background-color .16s ease;
}
.primary-entry-icon {
  width: 24px;
  height: 24px;
  flex: 0 0 24px;
  border: 1px solid transparent;
  border-radius: 7px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--app-font-size-section-title);
  overflow: hidden;
  transition: color .16s ease, border-color .16s ease, background-color .16s ease;
}
.primary-entry::after {
  content: '';
  position: absolute;
  left: 13px;
  right: 13px;
  bottom: 0;
  height: 2px;
  border-radius: 2px 2px 0 0;
  background: var(--shell-accent);
  opacity: 0;
  transform: scaleX(.35);
  transition: opacity .16s ease, transform .16s ease;
}
.primary-entry:hover {
  color: var(--chrome-text-strong);
  background: color-mix(in srgb, var(--chrome-bg-soft-hover) 42%, transparent);
}
.primary-entry.is-active {
  color: var(--chrome-text-strong);
}
.primary-entry.is-active .primary-entry-icon {
  border-color: var(--chrome-menu-icon-active-border);
  background: var(--chrome-menu-icon-active-bg);
  color: var(--chrome-menu-icon-active-color);
}
.primary-entry.is-active::after {
  opacity: 1;
  transform: scaleX(1);
}
.top-navigation.is-secondary {
  flex: none;
  height: 45px;
  gap: var(--app-space-control-gap);
  padding: 0 24px;
  border-bottom: 1px solid var(--chrome-border);
  background: var(--chrome-context-bar-bg);
  color: var(--chrome-text);
}
.secondary-context {
  flex: none;
  margin-right: 8px;
  color: var(--chrome-text-muted);
  font-size: var(--app-font-size-tiny);
  font-weight: var(--app-font-weight-strong);
  letter-spacing: .13em;
  text-transform: uppercase;
}
.secondary-context::after {
  content: '';
  display: inline-block;
  width: 1px;
  height: 13px;
  margin-left: 13px;
  vertical-align: -2px;
  background: var(--chrome-border-strong);
}
.secondary-entry {
  height: 30px;
  padding: 0 11px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--chrome-text);
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-control-gap);
  font-size: var(--app-font-size-caption);
  font-weight: var(--app-font-weight-section);
  white-space: nowrap;
  cursor: pointer;
  transition: color .16s ease, border-color .16s ease, background-color .16s ease;
}
.secondary-entry .el-icon { font-size: var(--app-icon-size-xs); }
.secondary-entry-icon {
  width: 19px;
  height: 19px;
  flex: 0 0 19px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--app-font-size-table) !important;
  color: var(--chrome-text-muted);
  overflow: hidden;
}
.secondary-entry:hover {
  color: var(--chrome-text-strong);
  background: var(--chrome-bg-soft-hover);
}
.secondary-entry.is-active {
  border-color: color-mix(in srgb, var(--shell-accent) 34%, var(--chrome-border));
  background: var(--chrome-active-bg);
  color: var(--chrome-text-strong);
  box-shadow: inset 0 -2px var(--shell-accent);
}
.secondary-entry.is-active .secondary-entry-icon {
  color: var(--chrome-menu-icon-active-color);
}
@container app-viewport (max-width: 960px) {
  .top-navigation.is-primary { padding-inline: 2px; }
  .primary-entry { padding-inline: 9px; }
  .primary-entry::after { left: 9px; right: 9px; }
  .secondary-context { display: none; }
}
</style>

<style>
.top-navigation-dropdown .el-dropdown-menu__item.is-active {
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  font-weight: var(--app-font-weight-section);
}
.top-navigation-dropdown .dropdown-entry-icon {
  width: 18px;
  height: 18px;
  margin-right: 7px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--app-font-size-table);
}
</style>
