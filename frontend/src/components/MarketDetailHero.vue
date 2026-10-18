<script setup lang="ts">
import AppScrollArea from '@/components/AppScrollArea.vue'
withDefaults(defineProps<{
  title: string
  code: string
  subtitle?: string
  asideAlign?: 'start' | 'end'
}>(), {
  subtitle: '',
  asideAlign: 'end',
})

defineSlots<{
  badges?: () => unknown
  actions?: () => unknown
  summary?: () => unknown
  meta?: () => unknown
  footer?: () => unknown
}>()
</script>

<template>
  <section class="market-detail-hero" :class="`market-detail-hero--aside-${asideAlign}`">
    <div class="market-detail-hero__main">
      <div class="market-detail-hero__copy">
        <div class="market-detail-hero__title-row">
          <h2 class="app-page-title">{{ title }}</h2>
          <slot name="badges" />
          <span class="market-detail-hero__code">{{ code }}</span>
          <slot name="actions" />
        </div>
        <p v-if="subtitle" class="market-detail-hero__subtitle">{{ subtitle }}</p>
      </div>
      <AppScrollArea v-if="$slots.summary || $slots.meta" class="market-detail-hero__aside">
        <slot name="summary" />
        <div v-if="$slots.meta" class="market-detail-hero__meta app-caption-text">
          <slot name="meta" />
        </div>
      </AppScrollArea>
    </div>
    <div v-if="$slots.footer" class="market-detail-hero__footer">
      <slot name="footer" />
    </div>
  </section>
</template>

<style scoped>
.market-detail-hero {
  flex: 0 0 auto;
  min-width: 0;
  border: 1px solid var(--el-border-color);
  border-radius: var(--layout-card-radius);
  background: var(--el-bg-color);
}

.market-detail-hero__main {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-4);
  padding: var(--app-space-3) var(--app-space-4);
}

.market-detail-hero--aside-start .market-detail-hero__main {
  justify-content: flex-start;
}

.market-detail-hero__copy {
  min-width: 0;
}

.market-detail-hero__aside {
  min-width: 0;
}

.market-detail-hero__aside {
  --app-scroll-display: flex;
  --app-scroll-align: center;
  --app-scroll-gap: var(--app-space-3);
}

.market-detail-hero__title-row {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
}

.market-detail-hero__code {
  color: var(--el-text-color-secondary);
  font-family: var(--app-font-family-mono);
  font-size: var(--app-font-size-caption);
}

.market-detail-hero__subtitle {
  margin: var(--app-space-1) 0 0;
  color: var(--el-text-color-secondary);
}

.market-detail-hero__meta {
  white-space: nowrap;
}

.market-detail-hero__footer {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--app-space-3);
  padding: var(--app-space-2) var(--app-space-4);
  border-top: 1px solid var(--el-border-color-lighter);
  background: color-mix(in srgb, var(--el-bg-color) 82%, transparent);
}

@container app-viewport (max-width: 980px) {
  .market-detail-hero__main {
    align-items: flex-start;
    flex-direction: column;
  }

  .market-detail-hero__aside {
    width: 100%;
  }
}
</style>
