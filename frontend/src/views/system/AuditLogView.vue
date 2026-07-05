<script setup lang="ts">
import { ref } from 'vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import { usePageSettings } from '@/composables/usePageSettings'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { getPageLayout } from '@/layout'
import LayoutHost from '@/layout/components/LayoutHost.vue'

const pageKey = 'audit-log'
const baseLayout = getPageLayout(pageKey)
const {
  effective,
  knobs: layoutKnobs,
  setKnob,
  valueOf,
  sourceOf,
  isDirty: layoutDirty,
  resetAll: resetLayout,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  layerValuesOf,
  componentLayerValuesOf,
} = useRemoteLayoutConfig(baseLayout)
const drawerConfig = {
  knobs: layoutKnobs,
  valueOf,
  sourceOf,
  setKnob,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  layerValuesOf,
  componentLayerValuesOf,
}
const { reset: resetBiz } = usePageSettings(pageKey, {})
const settingsOpen = ref(false)
</script>

<template>
  <LayoutHost :layout="effective">
    <template #action>
      <div class="system-page-head">
        <h2>审计日志</h2>
        <PageSettingsTrigger :dirty="layoutDirty" @click="settingsOpen = true" />
      </div>
    </template>

    <template #summary>
      <div class="audit-shell audit-shell--summary">
        <el-skeleton :rows="1" animated />
      </div>
    </template>

    <template #filters>
      <div class="audit-shell audit-shell--filters" />
    </template>

    <template #auditTable>
      <div class="system-shell-main">
        <el-empty class="app-empty" description="暂无记录" />
      </div>
    </template>

    <template #overlays>
      <PageSettingsDrawer
        v-model="settingsOpen"
        title="审计日志"
        :dirty="layoutDirty"
        :page-key="pageKey"
        :config="drawerConfig"
        @reset="resetBiz(); resetLayout()"
      />
    </template>
  </LayoutHost>
</template>

<style scoped>
.system-page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.system-page-head h2 {
  margin: 0;
  font-size: 20px;
}
.audit-shell {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-bg-color-overlay);
}
.audit-shell--summary {
  padding: 14px 16px;
}
.audit-shell--filters {
  min-height: 44px;
}
.system-shell-main {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-bg-color-overlay);
}
</style>
