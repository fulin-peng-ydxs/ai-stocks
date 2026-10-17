<script setup lang="ts">
import { vReveal } from '@/directives/reveal'
import { computed, nextTick, ref, watch } from 'vue'
import AppStateBlock from './AppStateBlock.vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  useWorkspaceTabs,
  trackWorkspaceRouteVisit,
  WORKSPACE_TAB_LIMIT,
} from '@/composables/useWorkspaceTabs'

const route = useRoute()
const auth = useAuthStore()
const { workspaceTabs, workspaceCacheNames, workspaceViewWrapper } = useWorkspaceTabs()
const hasActiveTab = computed(() => workspaceTabs.value.some(tab => tab.key === route.path))
const emptyWorkspace = ref<HTMLElement>()
watch(hasActiveTab, (active, previous) => {
  if (!active && previous) void nextTick(() => emptyWorkspace.value?.focus())
})
// 路由追踪与折叠状态解耦；关闭最后一页后保持空态，直到下一次显式导航。
watch(
  () => [route.fullPath, auth.menusStatus, auth.menus] as const,
  () => {
    if (auth.menusStatus !== 'ready') return
    trackWorkspaceRouteVisit(route, auth.menus)
  },
  { immediate: true },
)

</script>

<template>
  <div v-reveal:page="route.path" class="workspace-route-view">
    <router-view v-slot="{ Component }">
      <keep-alive :include="workspaceCacheNames" :max="WORKSPACE_TAB_LIMIT">
        <component
          :is="workspaceViewWrapper(route.path)"
          v-if="Component && hasActiveTab"
          :key="route.path"
          :view="Component"
        />
      </keep-alive>
    </router-view>
    <div v-if="!hasActiveTab" ref="emptyWorkspace" class="workspace-empty" tabindex="-1" role="region" aria-label="空工作区">
      <AppStateBlock state="empty" size="compact" description="工作区已清空，可从导航菜单选择页面继续研究。" />
    </div>
  </div>
</template>

<style scoped>
.workspace-route-view {
  display: contents;
}
.workspace-empty {
  height: 100%;
  min-height: 0;
  display: grid;
  place-items: center;
  padding: var(--app-space-5);
}
</style>
