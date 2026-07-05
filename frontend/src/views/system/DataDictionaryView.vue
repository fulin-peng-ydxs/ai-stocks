<script setup lang="ts">
import { ref } from 'vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import { usePageSettings } from '@/composables/usePageSettings'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { getPageLayout } from '@/layout'
import LayoutHost from '@/layout/components/LayoutHost.vue'

const pageKey = 'data-dictionary'
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
        <h2>数据字典</h2>
        <PageSettingsTrigger :dirty="layoutDirty" @click="settingsOpen = true" />
      </div>
    </template>

    <template #main>
      <div class="dict-shell-workspace">
        <div class="dict-shell-side">
          <el-empty class="app-empty app-empty--compact" description="暂无类型" />
        </div>
        <div class="dict-shell-main">
          <el-empty class="app-empty" description="暂无字典项" />
        </div>
      </div>
    </template>

    <template #overlays>
      <PageSettingsDrawer
        v-model="settingsOpen"
        title="数据字典"
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
.dict-shell-workspace {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  gap: 14px;
  overflow: auto;
}
.dict-shell-side,
.dict-shell-main {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-bg-color-overlay);
}
.dict-shell-side {
  flex: 0 0 280px;
  min-width: 240px;
}
.dict-shell-main {
  min-width: 520px;
}
</style>
