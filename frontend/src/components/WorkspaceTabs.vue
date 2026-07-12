<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Close } from '@element-plus/icons-vue'
import {
  removeWorkspaceTab,
  useWorkspaceTabs,
} from '@/composables/useWorkspaceTabs'

const route = useRoute()
const router = useRouter()
const { workspaceTabs } = useWorkspaceTabs()
const rail = ref<HTMLElement>()

watch(
  () => [route.path, workspaceTabs.value.length] as const,
  () => {
    void nextTick(() => {
      const activeTab = rail.value?.querySelector<HTMLElement>('.workspace-tab.is-active')
      if (typeof activeTab?.scrollIntoView === 'function') {
        activeTab.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' })
      }
    })
  },
  { immediate: true, flush: 'post' },
)

function activate(path: string) {
  if (path !== route.fullPath) void router.push(path)
}

function close(key: string) {
  const nextPath = removeWorkspaceTab(key, route.path)
  if (nextPath) void router.push(nextPath)
}
</script>

<template>
  <div v-if="workspaceTabs.length" class="workspace-tabs" aria-label="已打开页面">
    <span class="workspace-tabs-label" aria-hidden="true">WORKSPACE</span>
    <div ref="rail" class="workspace-tabs-rail" role="tablist">
      <div
        v-for="tab in workspaceTabs"
        :key="tab.key"
        class="workspace-tab"
        :class="{ 'is-active': tab.key === route.path }"
        role="tab"
        :tabindex="tab.key === route.path ? 0 : -1"
        :aria-selected="tab.key === route.path"
        @click="activate(tab.path)"
        @keydown.enter="activate(tab.path)"
        @keydown.space.prevent="activate(tab.path)"
      >
        <span class="workspace-tab-title">{{ tab.title }}</span>
        <button
          v-if="workspaceTabs.length > 1"
          class="workspace-tab-close"
          type="button"
          :aria-label="`关闭 ${tab.title}`"
          @click.stop="close(tab.key)"
        >
          <el-icon><Close /></el-icon>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.workspace-tabs {
  flex: none;
  height: 45px;
  min-width: 0;
  padding: 0 18px 0 21px;
  border-bottom: 1px solid var(--chrome-border);
  background: color-mix(in srgb, var(--chrome-bg) 92%, var(--el-bg-color-page) 8%);
  display: flex;
  align-items: center;
  gap: 13px;
}
.workspace-tabs-label {
  flex: none;
  color: var(--chrome-text-muted);
  font-size: 9px;
  font-weight: 750;
  letter-spacing: .14em;
}
.workspace-tabs-rail {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 5px;
  overflow-x: auto;
  scrollbar-width: none;
}
.workspace-tabs-rail::-webkit-scrollbar { display: none; }
.workspace-tab {
  position: relative;
  flex: none;
  height: 31px;
  max-width: 210px;
  padding: 0 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--chrome-text-muted);
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  cursor: pointer;
  transition: color .15s ease, background-color .15s ease, border-color .15s ease;
}
.workspace-tab::before {
  content: '';
  width: 4px;
  height: 4px;
  flex: none;
  border-radius: 50%;
  background: var(--chrome-border-strong);
}
.workspace-tab:hover {
  color: var(--chrome-text);
  background: var(--chrome-bg-soft-hover);
}
.workspace-tab.is-active {
  border-color: color-mix(in srgb, var(--shell-accent) 30%, var(--chrome-border));
  background: var(--chrome-active-bg);
  color: var(--chrome-text-strong);
  box-shadow: inset 0 -2px var(--shell-accent);
}
.workspace-tab.is-active::before {
  background: var(--shell-accent);
  box-shadow: 0 0 0 3px var(--shell-accent-faint);
}
.workspace-tab-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.workspace-tab-close {
  width: 16px;
  height: 16px;
  flex: none;
  padding: 0;
  border: 0;
  background: transparent;
  border-radius: 5px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--chrome-text-muted);
  opacity: 0;
}
.workspace-tab:hover .workspace-tab-close,
.workspace-tab.is-active .workspace-tab-close,
.workspace-tab-close:focus-visible { opacity: 1; }
.workspace-tab-close:hover {
  background: color-mix(in srgb, var(--el-color-danger) 12%, transparent);
  color: var(--el-color-danger);
}
.workspace-tab-close .el-icon { font-size: 11px; }
@media (max-width: 720px) {
  .workspace-tabs { padding-inline: 10px; }
  .workspace-tabs-label { display: none; }
}
</style>
