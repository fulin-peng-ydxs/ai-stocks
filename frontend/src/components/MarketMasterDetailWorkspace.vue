<script setup lang="ts">
import { computed } from 'vue'
import { DArrowLeft, DArrowRight } from '@element-plus/icons-vue'
import AppIconButton from '@/components/AppIconButton.vue'

const props = defineProps<{
  analysisVisible: boolean
  compact?: boolean
  eyebrow: string
  title: string
  meta?: string
  listAriaLabel?: string
}>()

const emit = defineEmits<{
  'update:analysisVisible': [visible: boolean]
}>()

function toggleAnalysis(): void {
  emit('update:analysisVisible', !props.analysisVisible)
}

const renderAnalysis = computed(() => props.analysisVisible && !props.compact)
</script>

<template>
  <div
    class="market-master-detail"
    :class="{ 'market-master-detail--list-only': !renderAnalysis }"
  >
    <section class="market-list-panel" :aria-label="listAriaLabel || title">
      <header class="market-list-head">
        <div>
          <div class="market-panel-eyebrow">{{ eyebrow }}</div>
          <h3 class="app-section-title">{{ title }}</h3>
        </div>
        <div class="market-list-actions">
          <span v-if="meta" class="app-caption-text">{{ meta }}</span>
          <AppIconButton
            v-if="!compact"
            :label="analysisVisible ? '收起走势分析，仅看列表' : '显示走势分析'"
            :data-testid="analysisVisible ? 'market-hide-analysis' : 'market-show-analysis'"
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

    <slot v-if="renderAnalysis" name="analysis" />
  </div>
</template>

<style scoped>
.market-master-detail {
  display: grid;
  grid-template-columns: minmax(360px, 0.82fr) minmax(0, 1.18fr);
  gap: var(--app-space-3);
  min-width: 860px;
  min-height: 0;
  height: 100%;
  overflow-x: auto;
}
.market-master-detail--list-only {
  grid-template-columns: minmax(0, 1fr);
  min-width: 640px;
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
@media (max-width: 1180px) {
  .market-list-actions > span {
    display: none;
  }
}
</style>
