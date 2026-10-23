<script setup lang="ts">
withDefaults(defineProps<{
  title?: string
  description?: string
  bordered?: boolean
}>(), {
  title: '',
  description: '',
  bordered: true,
})
</script>

<template>
  <section class="app-detail-section" :class="{ 'app-detail-section--bordered': bordered }">
    <header v-if="title || description || $slots.actions" class="app-detail-section__header">
      <div>
        <h3 v-if="title">{{ title }}</h3>
        <p v-if="description">{{ description }}</p>
      </div>
      <div v-if="$slots.actions" class="app-detail-section__actions"><slot name="actions" /></div>
    </header>
    <div class="app-detail-section__content app-body-text"><slot /></div>
  </section>
</template>

<style scoped>
.app-detail-section {
  display: grid;
  min-width: 0;
  gap: var(--app-space-3);
}
.app-detail-section--bordered {
  padding-top: var(--app-space-4);
  border-top: 1px solid var(--el-border-color-lighter);
}
.app-detail-section__header {
  display: flex;
  min-width: 0;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-3);
}
/* 标题区必须允许收缩；长任务名、版本标识等不能撑宽所属详情抽屉。 */
.app-detail-section__header > div:first-child { min-width: 0; }
.app-detail-section__header h3 {
  overflow-wrap: anywhere;
  margin: 0;
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-section-title);
  line-height: var(--app-line-height-section-title);
}
.app-detail-section__header p {
  margin: var(--app-space-1) 0 0;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-comfy);
}
.app-detail-section__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--app-space-2);
}
.app-detail-section__content { min-width: 0; }
.app-detail-section__content :deep(p) {
  margin: 0;
  color: var(--el-text-color-regular);
  line-height: var(--app-line-height-longform);
}
</style>
