<script setup lang="ts">
withDefaults(defineProps<{
  label?: string
  grow?: boolean
}>(), {
  label: '',
  grow: false,
})
</script>

<template>
  <div class="app-control-item" :class="{ 'is-grow': grow }">
    <span v-if="label || $slots.label" class="app-control-item__label">
      <slot name="label">{{ label }}</slot>
    </span>
    <span class="app-control-item__body">
      <slot />
    </span>
  </div>
</template>

<style scoped>
.app-control-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
  min-width: 0;
  max-width: 100%;
}
.app-control-item.is-grow {
  flex: 1 1 auto;
}
.app-control-item__label {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  flex: 0 0 auto;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  white-space: nowrap;
}
.app-control-item__body {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  max-width: 100%;
}
.app-control-item.is-grow .app-control-item__body {
  flex: 1 1 auto;
}
.app-control-item__body :deep(> *) {
  max-width: 100%;
}
</style>
