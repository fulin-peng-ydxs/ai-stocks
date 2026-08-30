<script setup lang="ts">
import { ref } from 'vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import MarketMasterDetailWorkspace from '@/components/MarketMasterDetailWorkspace.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { getPageLayout } from '@/layout'
import LayoutHost from '@/layout/components/LayoutHost.vue'

const settingsOpen = ref(false)
const analysisVisible = ref(true)
const baseLayout = getPageLayout('limit-ladder')
const {
  effective,
  knobs,
  setKnob,
  valueOf,
  sourceOf,
  layerValuesOf,
  isDirty,
  resetAll,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  componentLayerValuesOf,
  componentAllowedLayers,
} = useRemoteLayoutConfig(baseLayout)

const drawerConfig = {
  knobs,
  setKnob,
  valueOf,
  sourceOf,
  layerValuesOf,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  componentLayerValuesOf,
  componentAllowedLayers,
}
</script>

<template>
  <LayoutHost :layout="effective">
    <template #action>
      <div class="lh-action">
        <div class="page-head">
          <div>
            <div class="page-title-line">
              <h2 class="app-page-title">连板天梯</h2>
              <el-tag size="small" effect="plain">接入验证中</el-tag>
            </div>
            <p class="page-subtitle">按交易日观察涨停梯队，并在同一视野衔接个股走势研究。</p>
          </div>
          <PageSettingsTrigger :dirty="isDirty" @click="settingsOpen = true" />
        </div>
      </div>
    </template>

    <template #main>
      <MarketMasterDetailWorkspace
        v-model:analysis-visible="analysisVisible"
        eyebrow="LIMIT LADDER"
        title="涨停梯队"
        meta="页面能力分阶段接入"
        list-aria-label="连板天梯分层"
        data-testid="limit-ladder-workspace"
      >
        <template #list>
          <AppStateBlock
            state="empty"
            title="天梯展示即将接入"
            description="路由、布局与权限骨架已就绪，数据筛选和分层卡片将在下一阶段启用。"
          />
        </template>
        <template #analysis>
          <el-card
            shadow="never"
            class="analysis-placeholder"
            role="region"
            aria-label="股票走势分析"
          >
            <AppStateBlock
              state="empty"
              title="选择股票后查看走势"
              description="走势分析将在天梯卡片接入后启用。"
            />
          </el-card>
        </template>
      </MarketMasterDetailWorkspace>
    </template>

    <template #overlays>
      <PageSettingsDrawer
        v-model="settingsOpen"
        title="连板天梯"
        :dirty="isDirty"
        page-key="limit-ladder"
        :config="drawerConfig"
        :business-visible="false"
        @reset="resetAll"
      />
    </template>
  </LayoutHost>
</template>

<style scoped>
.page-title-line {
  display: flex;
  align-items: center;
}

.page-title-line {
  gap: var(--app-space-2);
}

.analysis-placeholder {
  display: flex;
  min-width: 0;
  min-height: 0;
  height: 100%;
}

.analysis-placeholder :deep(.el-card__body) {
  display: flex;
  width: 100%;
  min-height: 0;
}

.analysis-placeholder .app-state-block {
  flex: 1 1 auto;
}

@media (max-width: 720px) {
  .page-title-line {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
