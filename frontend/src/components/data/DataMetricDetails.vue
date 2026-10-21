<script setup lang="ts">
import AppHoverInfo from '@/components/AppHoverInfo'
import AppDetailFields from '@/components/AppDetailFields.vue'
import AppDetailField from '@/components/AppDetailField.vue'
import AppScrollArea from '@/components/AppScrollArea.vue'

defineProps<{
  label: string
  rows: { label: string; value: string }[]
  notes?: string[]
}>()
</script>

<template>
  <AppHoverInfo kind="popover" placement="bottom-start" :width="360">
    <template #reference>
      <span class="data-metric-details app-interaction-help" role="button" tabindex="0" :aria-label="`${label}统计详情`">i</span>
    </template>
    <AppScrollArea class="data-metric-detail-scroll" axis="y">
      <section class="data-metric-detail-content" :aria-label="`${label}统计详情`">
        <strong class="data-metric-detail-title">{{ label }}</strong>
        <AppDetailFields :columns="1">
          <AppDetailField v-for="row in rows" :key="row.label" :label="row.label" :value="row.value" />
        </AppDetailFields>
        <p v-for="note in notes" :key="note" class="data-metric-detail-note">{{ note }}</p>
      </section>
    </AppScrollArea>
  </AppHoverInfo>
</template>

<style scoped>
.data-metric-detail-scroll { max-height: calc(80vh / var(--app-display-scale, 1)); }
.data-metric-details {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 16px;
  height: 16px;
  border: 1px solid var(--el-border-color);
  border-radius: 50%;
  font-size: var(--app-font-size-caption);
  font-weight: var(--app-font-weight-section);
  line-height: var(--app-line-height-solid);
  cursor: help;
}
.data-metric-detail-title { display: block; margin-bottom: var(--app-space-2); font-size: var(--app-font-size-table); }
.data-metric-detail-note {
  margin: var(--app-space-2) 0 0;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-caption);
  overflow-wrap: anywhere;
}
</style>
