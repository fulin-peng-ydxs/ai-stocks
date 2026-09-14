<script setup lang="ts">
/**
 * 配置来源徽标——标注某项当前生效来自哪一层（default<page<user）。
 * 默认层用弱化样式，被某层覆盖时高亮，让用户一眼看出"这个值是谁定的"。
 */
import { computed } from 'vue'

type Source = 'default' | 'page' | 'user'
const props = defineProps<{
  source: Source
  values?: Partial<Record<Source, unknown>>
}>()
const LABELS: Record<Source, string> = { default: '默认', page: '页面', user: '个人' }
const ORDER: Source[] = ['default', 'page', 'user']

function formatValue(value: unknown): string {
  if (value === undefined) return '未设置'
  if (value === '') return '空'
  if (Array.isArray(value)) return value.length ? value.join(', ') : '空数组'
  if (value != null && typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

const rows = computed(() =>
  ORDER.map((layer) => ({ layer, label: LABELS[layer], value: formatValue(props.values?.[layer]) })),
)
</script>

<template>
  <el-tooltip placement="top" effect="light" popper-class="source-tag-popper">
    <template #content>
      <div class="source-pop">
        <div v-for="row in rows" :key="row.layer" class="source-row" :class="{ active: row.layer === source }">
          <span class="source-name app-caption-text">{{ row.label }}</span>
          <span class="source-value app-caption-text">{{ row.value }}</span>
        </div>
      </div>
    </template>
    <span class="source-tag app-micro-text" :class="`is-${source}`">{{ LABELS[source] }}</span>
  </el-tooltip>
</template>

<style scoped>
.source-tag {
  flex: none;
  font-size: var(--app-font-size-micro);
  line-height: var(--app-line-height-solid);
  padding: 2px 6px;
  border-radius: 999px;
  border: 1px solid var(--page-settings-border);
  color: var(--page-settings-text-muted);
}
/* 被某层覆盖：用主色描边提示"非代码默认"。 */
.source-tag.is-page,
.source-tag.is-user {
  color: var(--page-settings-accent);
  border-color: var(--page-settings-accent);
}
:global(.source-tag-popper) {
  max-width: 280px;
}
.source-pop {
  min-width: 180px;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
}
.source-row {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr);
  gap: var(--app-space-2);
  font-size: var(--app-font-size-caption);
}
.source-row.active .source-name,
.source-row.active .source-value {
  color: var(--el-color-primary);
  font-weight: var(--app-font-weight-section);
}
.source-name {
  color: var(--el-text-color-secondary);
}
.source-value {
  min-width: 0;
  color: var(--el-text-color-regular);
  overflow-wrap: anywhere;
}
</style>
