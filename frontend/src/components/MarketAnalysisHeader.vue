<script setup lang="ts">
import AppControlRow from '@/components/AppControlRow.vue'
import { ArrowRight } from '@element-plus/icons-vue'

withDefaults(defineProps<{
  title: string
  code?: string
  eyebrow?: string
  detailVisible?: boolean
  detailDisabled?: boolean
  titleTestId?: string
  detailTestId?: string
}>(), {
  code: '',
  eyebrow: '当前观察',
  detailVisible: false,
  detailDisabled: false,
  titleTestId: '',
  detailTestId: '',
})

const emit = defineEmits<{
  openDetail: []
}>()
</script>

<template>
  <div class="market-analysis-header">
    <header class="market-analysis-header__content" :class="{ 'market-analysis-header__content--with-summary': $slots.summary }">
      <div class="market-analysis-header__identity">
        <div class="market-analysis-header__eyebrow">{{ eyebrow }}</div>
        <div class="market-analysis-header__title-line">
          <h3 :data-testid="titleTestId || undefined">{{ title }}</h3>
          <span v-if="code">{{ code }}</span>
          <el-button data-button-kind="navigation"
            v-if="detailVisible"
            link
            type="primary"
            class="market-analysis-header__detail" size="small"
            :disabled="detailDisabled"
            :data-testid="detailTestId || undefined"
            @click="emit('openDetail')"
          >
            查看详情
            <el-icon class="el-icon--right"><ArrowRight /></el-icon>
          </el-button>
        </div>
        <div v-if="$slots.description" class="market-analysis-header__description">
          <slot name="description" />
        </div>
      </div>
      <div v-if="$slots.summary" class="market-analysis-header__summary">
        <slot name="summary" />
      </div>
      <AppControlRow v-if="$slots.controls" class="market-analysis-header__controls">
        <slot name="controls" />
      </AppControlRow>
    </header>
  </div>
</template>

<style scoped>
.market-analysis-header {
  flex: 0 0 auto;
  container-type: inline-size;
}
.market-analysis-header__content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-3);
  min-height: 72px;
  padding: var(--app-space-3) var(--app-space-4);
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.market-analysis-header__identity {
  min-width: 0;
}
.market-analysis-header__content--with-summary {
  display: grid;
  grid-template-columns: minmax(0, auto) minmax(0, 1fr) auto;
}
.market-analysis-header__summary {
  min-width: 0;
  min-height: calc(4 * var(--app-line-height-table) + 3 * var(--app-space-control-gap));
  display: flex;
  align-items: center;
  padding-left: var(--app-space-4);
  border-left: 1px solid var(--app-border-divider);
}
.market-analysis-header__eyebrow {
  color: var(--el-color-primary);
  font-size: var(--app-font-size-micro);
  line-height: var(--app-line-height-micro);
  font-weight: var(--app-font-weight-strong);
  letter-spacing: 0.14em;
}
.market-analysis-header__title-line {
  display: flex;
  align-items: baseline;
  gap: var(--app-space-2);
}
.market-analysis-header__title-line h3 {
  overflow: hidden;
  margin: 0;
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-title-md);
  line-height: var(--app-line-height-title-md);
  font-weight: var(--app-font-weight-strong);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.market-analysis-header__title-line > span {
  color: var(--el-text-color-placeholder);
  font-family: var(--app-font-family-mono);
  font-size: var(--app-font-size-micro);
}
.market-analysis-header__detail {
  flex: 0 0 auto;
  height: auto;
  padding: 0;
}
.market-analysis-header__description {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-caption);
}
.market-analysis-header__controls {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: var(--app-space-2);
}
@container (max-width: 820px) {
  .market-analysis-header__content {
    align-items: flex-start;
    flex-direction: column;
  }
  .market-analysis-header__controls {
    width: 100%;
    flex-wrap: wrap;
  }
  .market-analysis-header__content--with-summary {
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
  }
  .market-analysis-header__content--with-summary .market-analysis-header__controls {
    grid-column: 2;
    grid-row: 1;
    width: auto;
  }
  .market-analysis-header__summary {
    grid-column: 1 / -1;
    grid-row: 2;
    padding: var(--app-space-3) 0 0;
    border-top: 1px solid var(--app-border-divider);
    border-left: 0;
  }
  .market-analysis-header__content--with-summary .market-analysis-header__description {
    display: block;
  }
  .market-analysis-header__description,
  .market-analysis-header__controls :deep(.market-analysis-control-label) {
    display: none;
  }
}
@container (max-width: 480px) {
  .market-analysis-header__content--with-summary {
    grid-template-columns: minmax(0, 1fr);
  }
  .market-analysis-header__content--with-summary .market-analysis-header__controls {
    grid-column: 1;
    grid-row: 2;
  }
  .market-analysis-header__content--with-summary .market-analysis-header__summary {
    grid-row: 3;
  }
}
@container app-viewport (max-height: 700px) {
  .market-analysis-header__content {
    min-height: 60px;
  }
}
</style>
