<script setup lang="ts">
defineProps<{
  title: string
  description?: string
}>()
</script>

<template>
  <section class="trade-discipline-section-panel">
    <header class="trade-discipline-section-panel__head">
      <div>
        <h4>{{ title }}</h4>
        <p v-if="description">{{ description }}</p>
      </div>
    </header>
    <div class="trade-discipline-section-panel__body" data-testid="trade-discipline-section-body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.trade-discipline-section-panel {
  min-width: 0;
}
.trade-discipline-section-panel__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-3);
}
.trade-discipline-section-panel__head h4 { margin: 0; font-size: var(--app-font-size-section); }
.trade-discipline-section-panel__head p {
  margin: var(--app-space-1) 0 0;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.trade-discipline-section-panel__body {
  min-width: 0;
  padding: var(--app-space-4);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--layout-card-radius);
  background: var(--el-bg-color);
}
@media (max-width: 760px) {
  .trade-discipline-section-panel__head { align-items: stretch; flex-direction: column; }
}
</style>
