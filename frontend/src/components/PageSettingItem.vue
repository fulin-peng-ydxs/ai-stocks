<script setup lang="ts">
import HelpHint from './HelpHint.vue'

withDefaults(defineProps<{
  label?: string
  hint?: string
  layout?: 'stacked' | 'inline'
}>(), {
  label: '',
  hint: '',
  layout: 'stacked',
})
</script>

<template>
  <div class="page-setting-item" :class="`is-${layout}`">
    <div v-if="label || $slots.label || hint || $slots.actions" class="psi-label-row">
      <span v-if="label || $slots.label" class="psi-label">
        <slot name="label">{{ label }}</slot>
      </span>
      <HelpHint v-if="hint" :text="hint" />
      <span v-if="$slots.actions" class="psi-actions"><slot name="actions" /></span>
    </div>
    <div class="psi-control"><slot /></div>
    <div v-if="$slots.help" class="psi-help"><slot name="help" /></div>
  </div>
</template>

<style scoped>
.page-setting-item {
  display: flex;
  min-width: 0;
  max-width: 100%;
  gap: var(--app-space-2);
}
.page-setting-item.is-stacked {
  flex-direction: column;
  align-items: stretch;
}
.page-setting-item.is-inline {
  min-height: var(--app-density-control-height);
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-density-control-gap);
}
.psi-label-row {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--app-space-control-gap);
}
.psi-label {
  min-width: 0;
  font-size: var(--app-font-size-table);
  line-height: var(--app-line-height-table);
  font-weight: var(--app-font-weight-medium);
  color: var(--page-settings-text-subtle);
}
.psi-actions {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-2);
}
.psi-control {
  min-width: 0;
  max-width: 100%;
}
.is-stacked > .psi-control {
  width: 100%;
}
.is-inline > .psi-control {
  flex: none;
  display: inline-flex;
  align-items: center;
}
.psi-help {
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-caption);
  color: var(--page-settings-text-muted);
}
</style>
