<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  useWorkspaceTabs,
  visitWorkspaceTab,
  WORKSPACE_TAB_LIMIT,
} from '@/composables/useWorkspaceTabs'

const route = useRoute()
const auth = useAuthStore()
const { workspaceTabs, workspaceCacheNames, workspaceViewWrapper } = useWorkspaceTabs()
const viewHost = ref<HTMLElement | null>(null)
const scrollPositions = new Map<string, number>()

function scrollContainer(): HTMLElement | null {
  return viewHost.value?.parentElement ?? null
}

// 路由追踪与标签栏是否显示解耦：双顶模式访问的页面切回侧栏后仍在工作区中。
watch(
  () => [route.fullPath, auth.menusStatus, auth.menus] as const,
  () => {
    if (auth.menusStatus === 'ready') visitWorkspaceTab(route, auth.menus)
  },
  { immediate: true },
)

// el-main 是所有路由共用的滚动容器，KeepAlive 不会替它保存 scrollTop；按标签路径单独记忆现场。
watch(
  () => route.path,
  async (path, previousPath) => {
    const container = scrollContainer()
    if (container && previousPath && workspaceTabs.value.some((tab) => tab.key === previousPath)) {
      scrollPositions.set(previousPath, container.scrollTop)
    }
    await nextTick()
    const nextContainer = scrollContainer()
    if (nextContainer) nextContainer.scrollTop = scrollPositions.get(path) ?? 0
  },
)

watch(
  () => workspaceTabs.value.map((tab) => tab.key),
  (keys) => {
    const activeKeys = new Set(keys)
    for (const key of scrollPositions.keys()) {
      if (!activeKeys.has(key)) scrollPositions.delete(key)
    }
  },
)

onBeforeUnmount(() => scrollPositions.clear())
</script>

<template>
  <div ref="viewHost" class="workspace-route-view">
    <router-view v-slot="{ Component }">
      <keep-alive :include="workspaceCacheNames" :max="WORKSPACE_TAB_LIMIT">
        <component
          :is="workspaceViewWrapper(route.path)"
          v-if="Component"
          :key="route.path"
          :view="Component"
        />
      </keep-alive>
    </router-view>
  </div>
</template>

<style scoped>
.workspace-route-view {
  display: contents;
}
</style>
