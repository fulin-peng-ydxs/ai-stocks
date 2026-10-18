<script setup lang="ts">
import AppScrollArea from '@/components/AppScrollArea.vue'
import { vKeyboardActivate } from '@/directives/keyboardActivate'
import { acceptsKeyboardEvent } from '@/utils/keyboard'
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppCloseButton from './AppCloseButton.vue'
import AppIconButton from './AppIconButton.vue'
import { ArrowRight, Delete } from '@element-plus/icons-vue'
import { useWorkspaceTabPreferences } from '@/composables/useWorkspaceTabPreferences'
import MenuIcon from './MenuIcon.vue'
import { useAuthStore } from '@/stores/auth'
import { findMenuLeaf } from '@/utils/permission'
import {
  clearWorkspaceTabs,
  removeWorkspaceTab,
  useWorkspaceTabs,
} from '@/composables/useWorkspaceTabs'
import { permitNextRouteLeave } from '@/composables/useUnsavedChangesGuard'

const route = useRoute()
const router = useRouter()
const { workspaceTabs } = useWorkspaceTabs()
const { collapsed, setCollapsed } = useWorkspaceTabPreferences()
const auth = useAuthStore()
// 图标跟随授权菜单更新，详情页沿用所属菜单；不把菜单展示信息写进标签缓存。
const tabIcons = computed(() => new Map(workspaceTabs.value.map((tab) => [
  tab.key, findMenuLeaf(auth.menus, tab.key)?.icon || 'Document',
])))
const scrollArea = ref<InstanceType<typeof AppScrollArea>>()
const rail = computed(() => scrollArea.value?.viewport)
const focusedKey = ref(route.path)
const tabStop = computed(() => workspaceTabs.value.some(tab => tab.key === focusedKey.value)
  ? focusedKey.value : workspaceTabs.value.find(tab => tab.key === route.path)?.key ?? workspaceTabs.value[0]?.key)
watch(() => route.path, path => { focusedKey.value = path })
const closingKeys = ref(new Set<string>())
const clearing = ref(false)
watch(collapsed, () => { void nextTick(revealActiveTab) })

function revealActiveTab() {
  const container = rail.value
  const activeTab = container?.contains(document.activeElement) && document.activeElement?.matches('.workspace-tab')
    ? document.activeElement as HTMLElement
    : container?.querySelector<HTMLElement>('.workspace-tab.is-active')
  if (!container || !activeTab || !container.clientWidth) return
  // 同一定位容器内使用布局坐标，避免 CSS zoom 下 scrollIntoView 的偏差；仅滚动被裁掉的距离。
  const left = activeTab.offsetLeft
  const right = left + activeTab.offsetWidth
  if (left < container.scrollLeft) container.scrollLeft = left
  else if (right > container.scrollLeft + container.clientWidth) {
    container.scrollLeft = right - container.clientWidth
  }
}

watch(rail, (container, _, onCleanup) => {
  if (!container || typeof ResizeObserver === 'undefined') return
  const observer = new ResizeObserver(revealActiveTab)
  observer.observe(container)
  onCleanup(() => observer.disconnect())
}, { flush: 'post' })

watch(
  () => [route.path, workspaceTabs.value.length] as const,
  () => { void nextTick(revealActiveTab) },
  { immediate: true, flush: 'post' },
)

function activate(path: string) {
  if (path !== route.fullPath) void router.push(path)
}

function onTabKeydown(event: KeyboardEvent, key: string) {
  if (event.target !== event.currentTarget || !acceptsKeyboardEvent(event, true)) return
  const tabs = workspaceTabs.value
  const index = tabs.findIndex(tab => tab.key === key)
  let next: number
  if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length
  else if (event.key === 'ArrowRight') next = (index + 1) % tabs.length
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = tabs.length - 1
  else return
  event.preventDefault()
  focusedKey.value = tabs[next].key
  // 手动激活：方向键只移动焦点；Enter/空格复用 click，避免浏览标签即触发页面请求。
  rail.value?.querySelectorAll<HTMLElement>('[role="tab"]')[next]?.focus()
  revealActiveTab()
}

async function close(key: string) {
  if (clearing.value || closingKeys.value.has(key)) return
  closingKeys.value.add(key)
  try {
    const restoreFocus = rail.value?.contains(document.activeElement)
    const nextPath = await removeWorkspaceTab(key, route.path)
    if (nextPath) {
      permitNextRouteLeave(key)
      await router.push(nextPath)
    }
    await nextTick()
    // 仅在触发入口已被移除时恢复到当前标签；取消离开和用户已交接的焦点保持原状。
    if (restoreFocus && !workspaceTabs.value.some(tab => tab.key === key)
      && (document.activeElement === document.body || !document.activeElement?.isConnected)) {
      rail.value?.querySelector<HTMLElement>('.workspace-tab.is-active')?.focus()
    }
  } finally { closingKeys.value.delete(key) }
}

async function clear() {
  if (clearing.value || closingKeys.value.size) return
  clearing.value = true
  try { await clearWorkspaceTabs() }
  finally { clearing.value = false }
}
</script>

<template>
  <div v-if="workspaceTabs.length" class="workspace-tabs" :class="{ 'is-collapsed': collapsed }" aria-label="已打开页面">
    <div class="workspace-tabs-heading">
      <AppIconButton
        :label="collapsed ? '展开工作区' : '收起工作区'"
        :tooltip="collapsed ? '展开工作区' : '收起工作区'"
        :aria-expanded="!collapsed"
        size="xs"
        @click="setCollapsed(!collapsed)"
      ><ArrowRight class="workspace-tabs-chevron" /></AppIconButton>
      <span class="workspace-tabs-label">工作区</span>
      <span class="workspace-tabs-count" :aria-label="`${workspaceTabs.length} 个已打开页面`">{{ workspaceTabs.length }}</span>
      <AppIconButton
        label="清空页签"
        tooltip="清空所有页签"
        size="xs"
        :loading="clearing"
        :disabled="closingKeys.size > 0"
        @click="clear"
      ><Delete /></AppIconButton>
      <span v-if="!collapsed" class="workspace-tabs-divider" aria-hidden="true">｜</span>
    </div>
    <Transition name="workspace-tabs-rail" @after-enter="revealActiveTab">
      <AppScrollArea v-show="!collapsed" ref="scrollArea" axis="x" class="workspace-tabs-rail" role="tablist" :aria-hidden="collapsed" :inert="collapsed ? '' : undefined">
        <div
          v-for="tab in workspaceTabs"
          :key="tab.key"
          class="workspace-tab app-nav-context-entry app-interaction-target app-interaction-nav"
          :class="{ 'is-active': tab.key === route.path }"
          role="tab"
          :tabindex="tab.key === tabStop ? 0 : -1"
          @focus="focusedKey = tab.key"
          :aria-selected="tab.key === route.path"
          @click="activate(tab.path)"
          v-keyboard-activate
          @keydown="onTabKeydown($event, tab.key)"
        >
          <MenuIcon class="workspace-tab-icon app-interaction-content" :name="tabIcons.get(tab.key)" />
          <span class="workspace-tab-title app-interaction-content">{{ tab.title }}</span>
          <AppCloseButton
            class="workspace-tab-close"
            size="inline"
            :label="`关闭 ${tab.title}`"
            @click.stop="close(tab.key)"
            :disabled="clearing || closingKeys.has(tab.key)"
          />
        </div>
      </AppScrollArea>
    </Transition>
  </div>
</template>

<style scoped>
.workspace-tabs {
  flex: none;
  height: var(--app-nav-context-bar-height);
  min-width: 0;
  padding: 0 var(--app-space-5);
  border-bottom: 1px solid var(--chrome-border);
  background: var(--chrome-context-bar-bg);
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  overflow: clip;
  /* 栏高直接落到终态，避免整页图表与滚动区在动画每一帧重测尺寸。 */
}
.workspace-tabs.is-collapsed { height: var(--app-control-height-sm); }
.workspace-tabs-chevron {
  transition: transform var(--app-motion-collapse) var(--app-motion-ease);
}
.workspace-tabs:not(.is-collapsed) .workspace-tabs-chevron { transform: rotate(90deg); }
.workspace-tabs-rail-enter-active,
.workspace-tabs-rail-leave-active {
  transition: opacity var(--app-motion-collapse) var(--app-motion-ease);
}
.workspace-tabs-rail-enter-from,
.workspace-tabs-rail-leave-to { opacity: 0; }
.workspace-tabs-heading {
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-control-gap);
  white-space: nowrap;
  color: var(--chrome-text);
  font-family: var(--app-nav-font-family);
  font-size: var(--app-nav-tab-font-size);
  line-height: var(--app-nav-meta-line-height);
  font-weight: var(--app-nav-weight-active);
}
.workspace-tabs-count {
  min-width: var(--app-control-height-xs);
  height: var(--app-control-height-xs);
  padding-inline: var(--app-space-1);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--app-control-height-xs);
  background: var(--shell-accent-faint);
  color: var(--shell-accent);
  font-size: var(--app-font-size-micro);
  font-variant-numeric: tabular-nums;
}
.workspace-tabs-divider {
  color: var(--chrome-border-strong);
  font-weight: var(--app-nav-weight-regular);
}
.workspace-tabs-rail {
  position: relative;
  --app-scroll-position: relative;
  min-width: 0;
  --app-scroll-display: flex;
  --app-scroll-align: center;
  --app-scroll-gap: var(--app-space-1);
  --app-scroll-padding-top: var(--app-nav-indicator-size); --app-scroll-padding-right: var(--app-nav-indicator-size); --app-scroll-padding-bottom: var(--app-nav-indicator-size); --app-scroll-padding-left: var(--app-nav-indicator-size);
  border: 1px solid var(--chrome-border);
  border-radius: var(--app-nav-item-radius);
  background: var(--chrome-bg-soft);
}
.workspace-tab {
  position: relative;
  flex: none;
  max-width: 180px;
  padding-inline: var(--app-space-3);
  --app-nav-entry-color: var(--chrome-text-muted);
  font-family: var(--app-nav-font-family);
  font-size: var(--app-nav-tab-font-size);
  line-height: var(--app-nav-meta-line-height);
  font-weight: var(--app-nav-weight-regular);
}
.workspace-tab.is-active {
  --app-interaction-nav-hover-background: var(--chrome-active-bg);
  background: var(--chrome-active-bg);
  border-color: var(--chrome-border-strong);
  box-shadow: inset 0 var(--app-nav-indicator-size) var(--shell-accent),
    var(--app-interaction-nav-shadow);
  font-weight: var(--app-nav-weight-active);
}
.workspace-tab-icon {
  flex: none;
  width: var(--app-icon-size-sm);
  height: var(--app-icon-size-sm);
  font-size: var(--app-icon-size-sm);
}
.workspace-tab.is-active .workspace-tab-icon { color: var(--shell-accent); }
.workspace-tab-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.workspace-tab-close {
  opacity: 0.4;
}
.workspace-tab:hover .workspace-tab-close,
.workspace-tab.is-active .workspace-tab-close,
.workspace-tab-close:focus-visible { opacity: 1; }
@media (hover: none), (pointer: coarse) {
  .workspace-tab-close { opacity: 1; }
}
@container app-viewport (max-width: 720px) {
  .workspace-tabs { padding-inline: var(--app-nav-entry-padding-x); }
}
</style>
