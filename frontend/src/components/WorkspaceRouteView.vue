<script setup lang="ts">
import { watch } from 'vue'
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
// 路由追踪与标签栏是否显示解耦：双顶模式访问的页面切回侧栏后仍在工作区中。
watch(
  () => [route.fullPath, auth.menusStatus, auth.menus] as const,
  () => {
    if (auth.menusStatus === 'ready') visitWorkspaceTab(route, auth.menus)
  },
  { immediate: true },
)

</script>

<template>
  <div class="workspace-route-view">
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
