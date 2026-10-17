<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppCloseButton from './AppCloseButton.vue'
import {
  removeWorkspaceTab,
  useWorkspaceTabs,
} from '@/composables/useWorkspaceTabs'
import { permitNextRouteLeave } from '@/composables/useUnsavedChangesGuard'

const route = useRoute()
const router = useRouter()
const { workspaceTabs } = useWorkspaceTabs()
const rail = ref<HTMLElement>()
const closingKeys = ref(new Set<string>())

function revealActiveTab() {
  const container = rail.value
  const activeTab = container?.querySelector<HTMLElement>('.workspace-tab.is-active')
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

async function close(key: string) {
  if (closingKeys.value.has(key)) return
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
</script>

<template>
  <div v-if="workspaceTabs.length" class="workspace-tabs" aria-label="已打开页面">
    <div ref="rail" class="workspace-tabs-rail" role="tablist">
      <div
        v-for="tab in workspaceTabs"
        :key="tab.key"
        class="workspace-tab app-nav-context-entry app-interaction-target app-interaction-nav"
        :class="{ 'is-active': tab.key === route.path }"
        role="tab"
        :tabindex="tab.key === route.path ? 0 : -1"
        :aria-selected="tab.key === route.path"
        @click="activate(tab.path)"
        @keydown.enter="activate(tab.path)"
        @keydown.space.prevent="activate(tab.path)"
      >
        <span class="workspace-tab-dot app-interaction-content" aria-hidden="true" />
        <span class="workspace-tab-title app-interaction-content">{{ tab.title }}</span>
        <AppCloseButton
          v-if="workspaceTabs.length > 1"
          class="workspace-tab-close"
          size="inline"
          :label="`关闭 ${tab.title}`"
          @click.stop="close(tab.key)"
          :disabled="closingKeys.has(tab.key)"
        />
      </div>
    </div>
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
  gap: var(--app-space-3);
}
.workspace-tabs-rail {
  position: relative;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--app-nav-entry-gap);
  overflow-x: auto;
  scrollbar-width: none;
  padding-block: var(--app-space-1);
}
.workspace-tabs-rail::-webkit-scrollbar { display: none; }
.workspace-tab {
  position: relative;
  flex: none;
  max-width: 210px;
  --app-nav-entry-color: var(--chrome-text-muted);
  font-family: var(--app-nav-font-family);
  font-size: var(--app-nav-tab-font-size);
  line-height: var(--app-nav-meta-line-height);
  font-weight: var(--app-nav-weight-regular);
}
.workspace-tab-dot {
  width: var(--app-nav-location-dot-size);
  height: var(--app-nav-location-dot-size);
  flex: none;
  border-radius: 50%;
  /* 保留圆点占位，只有当前项显示，避免切换标签时宽度跳动。 */
  background: transparent;
}
.workspace-tab.is-active {
  font-weight: var(--app-nav-weight-active);
}
.workspace-tab.is-active .workspace-tab-dot {
  background: var(--shell-accent);
}
.workspace-tab-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.workspace-tab-close { opacity: 0; }
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
