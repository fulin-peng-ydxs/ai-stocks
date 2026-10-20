<script setup lang="ts">
/** 表单辅助说明：标记独立占列，单行与多行采用同一排版，不承载校验错误。 */
withDefaults(defineProps<{ tone?: 'default' | 'warning' }>(), { tone: 'default' })
</script>

<template>
  <div class="app-form-help app-caption-text" :class="{ 'app-form-help--warning': tone === 'warning' }" role="note">
    <span class="app-form-help__marker" aria-hidden="true">*</span>
    <div class="app-form-help__content"><slot /></div>
  </div>
</template>

<style scoped>
.app-form-help {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  column-gap: var(--app-space-1);
  align-items: start;
  flex: 0 0 auto;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  margin-top: var(--app-space-1);
  text-align: start;
}
.app-form-help--warning { color: var(--app-warning-text); }
.app-form-help__content { min-width: 0; overflow-wrap: anywhere; }
</style>
