<script setup lang="ts">
import AppControlRow from '@/components/AppControlRow.vue'

defineProps<{ label: string }>()
</script>

<template>
  <div class="app-tab-toolbar" role="toolbar" :aria-label="label">
    <AppControlRow v-if="$slots.actions" class="app-tab-toolbar__actions" dense>
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
  min-height: 32px;
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
</style>
