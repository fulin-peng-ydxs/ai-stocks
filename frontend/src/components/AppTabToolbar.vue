<script setup lang="ts">
import AppControlRow from '@/components/AppControlRow.vue'
import { useControlRowSizing, type ControlRowSize } from './controlRowSizing'

withDefaults(defineProps<{
  label: string
  size?: ControlRowSize
  /** 筛选输入从左起排；纯命令组可在所属内容区右对齐。 */
  actionsAlign?: 'start' | 'end'
}>(), { actionsAlign: 'start' })
const row = useControlRowSizing()
</script>

<template>
  <div class="app-tab-toolbar app-control-row-scope" :style="row.style.value" :data-control-row="row.size.value" :class="{ 'is-actions-end': actionsAlign === 'end' }" role="toolbar" :aria-label="label">
    <AppControlRow v-if="$slots.actions" class="app-tab-toolbar__actions" :justify="actionsAlign">
      <slot name="actions" />
    </AppControlRow>
    <div v-if="$slots.description" class="app-tab-toolbar__description">
      <slot name="description" />
    </div>
  </div>
</template>

<style scoped>
.app-tab-toolbar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
  flex-wrap: wrap;
  min-width: 0;
  min-height: var(--app-control-row-height);
  margin-bottom: var(--app-space-2);
}
.app-tab-toolbar__actions {
  flex: 1 1 auto;
}
.app-tab-toolbar__description {
  flex: 0 1 auto;
  min-width: min(240px, 100%);
  margin-left: auto;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-body);
  text-align: right;
}
.is-actions-end .app-tab-toolbar__description {
  flex: 1 1 100%;
  margin-left: 0;
  text-align: left;
}
</style>
