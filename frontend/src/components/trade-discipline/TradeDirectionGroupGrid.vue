<script setup lang="ts">
export interface TradeDirectionGroup {
  value: 'buy' | 'sell'
  label: string
  hint: string
  testId: string
}

defineProps<{
  groups: TradeDirectionGroup[]
}>()
</script>

<template>
  <div class="trade-direction-group-grid">
    <section
      v-for="group in groups"
      :key="group.value"
      class="trade-direction-group"
      :data-testid="group.testId"
    >
      <header class="trade-direction-group__head">
        <div>
          <h5>{{ group.label }}</h5>
          <p>{{ group.hint }}</p>
        </div>
        <slot name="actions" :group="group" />
      </header>
      <div class="trade-direction-group__body">
        <slot :group="group" />
      </div>
    </section>
  </div>
</template>

<style scoped>
.trade-direction-group-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(300px, 1fr));
  gap: var(--app-space-3);
}
.trade-direction-group {
  min-width: 0;
  padding-top: var(--app-space-2);
  border-top: 1px solid var(--el-border-color);
  background: transparent;
}
.trade-direction-group__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-2);
  margin-bottom: var(--app-space-3);
}
.trade-direction-group h5 {
  margin: 0;
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-table);
}
.trade-direction-group p {
  margin: var(--app-space-1) 0 0;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.trade-direction-group__body { min-width: 0; }

@media (max-width: 1100px) {
  .trade-direction-group-grid { grid-template-columns: minmax(0, 1fr); }
}
</style>
