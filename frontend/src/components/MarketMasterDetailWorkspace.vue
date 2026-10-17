<script setup lang="ts">
import { computed, ref, useAttrs } from 'vue'
import { DArrowLeft, DArrowRight } from '@element-plus/icons-vue'
import AppIconButton from '@/components/AppIconButton.vue'
import AppSplitWorkspace from '@/components/AppSplitWorkspace.vue'
import AppWorkspacePane from '@/components/AppWorkspacePane.vue'
import type { MasterDetailRatioRuntimeSample } from '@/layout/masterDetailRatioProfiles'
import {
  MARKET_WORKSPACE_COMPACT_MIN_HEIGHT,
  MARKET_WORKSPACE_MIN_HEIGHT,
  type MarketWorkspaceHeightMode,
} from '@/layout/marketWorkspaceSizing'

const props = defineProps<{
  analysisVisible: boolean
  compact?: boolean
  eyebrow?: string
  title: string
  meta?: string
  listAriaLabel?: string
  defaultMasterRatio?: number
  masterRatioProfiles?: unknown
  analysisDrawerTitle?: string
  testIdPrefix?: string
  heightMode?: MarketWorkspaceHeightMode
}>()
defineOptions({ inheritAttrs: false })
const attrs = useAttrs()

const emit = defineEmits<{
  'update:analysisVisible': [visible: boolean]
  masterRatioChange: [ratio: number]
  masterRatioSampleChange: [sample: MasterDetailRatioRuntimeSample | undefined]
  compactAnalysisClose: []
}>()

function toggleAnalysis(): void {
  emit('update:analysisVisible', !props.analysisVisible)
}

const testIdPrefix = computed(() => props.testIdPrefix || 'market')
const splitWorkspaceRef = ref<InstanceType<typeof AppSplitWorkspace> | null>(null)

function openCompactAnalysis(): boolean {
  return splitWorkspaceRef.value?.openCompactSecondary() ?? false
}

function closeCompactAnalysis(): void {
  splitWorkspaceRef.value?.closeCompactSecondary()
}

defineExpose({ openCompactAnalysis, closeCompactAnalysis })
</script>

<template>
  <AppSplitWorkspace
    v-bind="attrs"
    ref="splitWorkspaceRef"
    class="market-master-detail"
    :secondary-visible="analysisVisible"
    :compact="compact"
    :default-primary-ratio="defaultMasterRatio"
    :primary-ratio-profiles="masterRatioProfiles"
    :primary-only-min-width="640"
    :min-height="MARKET_WORKSPACE_MIN_HEIGHT"
    :compact-min-height="MARKET_WORKSPACE_COMPACT_MIN_HEIGHT"
    :adaptive-height="heightMode === 'adaptive'"
    :secondary-drawer-title="analysisDrawerTitle || '走势分析'"
    separator-label="调整列表与走势分析宽度"
    :test-id-prefix="testIdPrefix"
    splitter-test-id="market-master-detail-splitter"
    :secondary-drawer-test-id="`${testIdPrefix}-analysis-drawer`"
    @update:secondary-visible="emit('update:analysisVisible', $event)"
    @primary-ratio-change="emit('masterRatioChange', $event)"
    @primary-ratio-sample-change="emit('masterRatioSampleChange', $event)"
    @compact-secondary-close="emit('compactAnalysisClose')"
  >
    <template #primary="{ compact: isCompact }">
      <AppWorkspacePane
        class="market-list-panel"
        :aria-label="listAriaLabel || title"
        :eyebrow="eyebrow"
        :title="title"
      >
        <template #actions>
          <div class="market-list-actions">
            <span v-if="meta" class="app-caption-text">{{ meta }}</span>
            <AppIconButton
              v-if="!isCompact"
              :label="analysisVisible ? '收起走势分析，仅看列表' : '显示走势分析'"
              :data-testid="analysisVisible ? `${testIdPrefix}-hide-analysis` : `${testIdPrefix}-show-analysis`"
              @click="toggleAnalysis"
            >
              <el-icon><DArrowRight v-if="analysisVisible" /><DArrowLeft v-else /></el-icon>
            </AppIconButton>
          </div>
        </template>
        <slot name="list" />
      </AppWorkspacePane>
    </template>

    <template #secondary><slot name="analysis" /></template>
  </AppSplitWorkspace>
</template>

<style scoped>
.market-master-detail {
  min-height: 0;
}
.market-list-actions {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
}
.market-list-actions > span {
  max-width: 180px;
  color: var(--el-text-color-secondary);
  text-align: right;
}
.market-list-panel :deep(.app-data-table) {
  flex: 1 1 auto;
  min-height: 0;
}
:deep(.el-table__row.stock-analysis-row--active > td.el-table__cell) {
  background: color-mix(in srgb, var(--el-color-primary-light-9) 72%, var(--el-bg-color));
}
:deep(.el-table__row.stock-analysis-row--active > td:first-child) {
  box-shadow: inset 3px 0 0 var(--el-color-primary);
}
@container app-viewport (max-width: 1180px) {
  .market-list-actions > span {
    display: none;
  }
}
</style>
