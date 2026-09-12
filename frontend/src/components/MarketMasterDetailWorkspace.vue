<script setup lang="ts">
import { computed, ref, useAttrs } from 'vue'
import { DArrowLeft, DArrowRight } from '@element-plus/icons-vue'
import AppIconButton from '@/components/AppIconButton.vue'
import AppSplitWorkspace from '@/components/AppSplitWorkspace.vue'
import type { MasterDetailRatioSample } from '@/layout/masterDetailRatioProfiles'

const props = defineProps<{
  analysisVisible: boolean
  compact?: boolean
  eyebrow: string
  title: string
  meta?: string
  listAriaLabel?: string
  defaultMasterRatio?: number
  masterRatioProfiles?: unknown
  analysisDrawerTitle?: string
  testIdPrefix?: string
}>()
defineOptions({ inheritAttrs: false })
const attrs = useAttrs()

const emit = defineEmits<{
  'update:analysisVisible': [visible: boolean]
  masterRatioChange: [ratio: number]
  masterRatioSampleChange: [sample: MasterDetailRatioSample | undefined]
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
      <section class="market-list-panel" :aria-label="listAriaLabel || title">
        <header class="market-list-head">
          <div>
            <div class="market-panel-eyebrow">{{ eyebrow }}</div>
            <h3 class="app-section-title">{{ title }}</h3>
          </div>
          <div class="market-list-actions">
            <span v-if="meta" class="app-caption-text">{{ meta }}</span>
            <AppIconButton
              v-if="!isCompact"
              :label="analysisVisible ? '收起走势分析，仅看列表' : '显示走势分析'"
              :data-testid="analysisVisible ? `${testIdPrefix}-hide-analysis` : `${testIdPrefix}-show-analysis`"
              :native-title="false"
              @click="toggleAnalysis"
            >
              <el-icon><DArrowRight v-if="analysisVisible" /><DArrowLeft v-else /></el-icon>
            </AppIconButton>
          </div>
        </header>
        <div class="market-list-body">
          <slot name="list" />
        </div>
      </section>
    </template>

    <template #secondary><slot name="analysis" /></template>
  </AppSplitWorkspace>
</template>

<style scoped>
.market-master-detail {
  min-height: 0;
}
.market-list-panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border: 1px solid var(--el-border-color);
  border-radius: var(--layout-card-radius);
  background: var(--el-bg-color);
}
.market-list-head {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-3);
  min-height: 64px;
  padding: var(--app-space-3) var(--app-space-4);
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: color-mix(in srgb, var(--el-color-primary-light-9) 42%, var(--el-bg-color));
}
.market-panel-eyebrow {
  color: var(--el-color-primary);
  font-size: var(--app-font-size-micro);
  line-height: var(--app-line-height-micro);
  font-weight: var(--app-font-weight-strong);
  letter-spacing: 0.14em;
}
.market-list-head h3 {
  margin: 0;
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
.market-list-body {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-height: 0;
}
.market-list-body :deep(.app-data-table) {
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
