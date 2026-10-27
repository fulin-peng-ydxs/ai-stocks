<script setup lang="ts">
import AppControlRow from '@/components/AppControlRow.vue'
withDefaults(defineProps<{
  title: string
  description?: string
  /** panel 统一外框；嵌入已有分区时用 none，避免重复边框与内距。 */
  borderPlacement?: 'body' | 'panel' | 'none'
  /** 空分区可只保留标题和动作；既有消费者默认继续展示正文。 */
  showBody?: boolean
}>(), { showBody: true, borderPlacement: 'body' })
</script>

<template>
  <section class="trade-discipline-section-panel" :class="{ 'is-header-only': showBody === false, 'is-panel-bordered': borderPlacement === 'panel', 'is-borderless': borderPlacement === 'none', 'app-surface': borderPlacement === 'panel' }">
    <header class="trade-discipline-section-panel__head">
      <div>
        <h4 class="app-section-title">{{ title }}</h4>
        <p v-if="description">{{ description }}</p>
      </div>
      <AppControlRow v-if="$slots.actions"><slot name="actions" /></AppControlRow>
    </header>
    <div v-if="showBody !== false" class="trade-discipline-section-panel__body" data-testid="trade-discipline-section-body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.trade-discipline-section-panel {
  min-width: 0;
}
.trade-discipline-section-panel.is-panel-bordered { padding: var(--layout-card-padding, var(--app-space-4)); }
.is-panel-bordered .trade-discipline-section-panel__body,
.is-borderless .trade-discipline-section-panel__body { padding: 0; border: 0; background: transparent; }
.trade-discipline-section-panel__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-3);
}

.trade-discipline-section-panel__head p {
  margin: var(--app-space-1) 0 0;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.trade-discipline-section-panel.is-header-only .trade-discipline-section-panel__head { margin-bottom: 0; }
.trade-discipline-section-panel__body {
  min-width: 0;
  padding: var(--app-space-4);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--layout-card-radius);
  background: var(--el-bg-color);
}
@container app-viewport (max-width: 760px) {
  .trade-discipline-section-panel__head { align-items: stretch; flex-direction: column; }
}
</style>
