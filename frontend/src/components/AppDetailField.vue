<script setup lang="ts">
withDefaults(defineProps<{
  label: string
  value?: unknown
  emptyText?: string
  span?: 'normal' | 'full'
  mono?: boolean
}>(), {
  value: undefined,
  emptyText: '—',
  span: 'normal',
  mono: false,
})
</script>

<template>
  <div class="app-detail-field" :class="{ 'app-detail-field--full': span === 'full' }">
    <dt>{{ label }}</dt>
    <dd :class="{ 'app-detail-field__value--mono': mono }">
      <slot>{{ value === null || value === undefined || value === '' ? emptyText : value }}</slot>
    </dd>
  </div>
</template>

<style scoped>
.app-detail-field {
  display: grid;
  grid-template-columns: minmax(96px, 32%) minmax(0, 1fr);
  min-width: 0;
  background: var(--el-bg-color);
  box-shadow: 0 0 0 1px var(--app-border-divider);
}
.app-detail-field--full { grid-column: 1 / -1; }
.app-detail-field dt,
.app-detail-field dd {
  min-width: 0;
  margin: 0;
  padding: var(--app-space-2) var(--app-space-3);
  overflow-wrap: anywhere;
}
.app-detail-field dt {
  color: var(--el-text-color-secondary);
  background: var(--app-section-bg);
  font-size: var(--app-font-size-caption);
}
.app-detail-field dd { color: var(--el-text-color-primary); }
.app-detail-field__value--mono { font-family: var(--app-font-family-mono); }
</style>
