<script setup lang="ts">
import { formatNumber } from '@/utils/numberFormat'
import { computed, inject, nextTick, onBeforeUnmount, ref, watch, watchEffect } from 'vue'
import { ArrowDown, ArrowUp } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import AppScrollArea from './AppScrollArea.vue'
import { useControlRowSizing, type ControlRowSize } from './controlRowSizing'
import { SEARCH_GROUPS, resolveCommonFields, searchSummary, type SearchFieldState, type SearchGroupKey } from '@/layout/searchGroups'
import { SEARCH_COMPONENT_VALUE, SEARCH_RUNTIME_META } from '@/layout/searchContext'

const props = defineProps<{ group: SearchGroupKey; states: Record<string, SearchFieldState>; size?: ControlRowSize }>()
const row = useControlRowSizing()
const componentValueOf = inject(SEARCH_COMPONENT_VALUE, undefined)
const runtimeMeta = inject(SEARCH_RUNTIME_META, undefined)
const definition = computed(() => SEARCH_GROUPS[props.group])
const expanded = ref(false)
const root = ref<HTMLElement>()
const fields = computed(() => definition.value.fields.filter((field) => props.states[field.key]?.available !== false && props.states[field.key]))
const enabled = computed(() => fields.value.length >= 3)
const common = computed(() => resolveCommonFields(
  componentValueOf?.(definition.value.slotId, 'commonFields'),
  fields.value, definition.value.defaults,
))
const advanced = computed(() => enabled.value ? fields.value.filter((field) => !common.value.includes(field.key)) : [])
const summaries = computed(() => advanced.value.map((field) => ({ ...field, text: searchSummary(props.states[field.key]) })).filter((field) => field.text))
// 所有字段始终处于同一个 keyed 父节点下。调整展示位置只移动 DOM，不重建远程选择器或丢失输入草稿。
const entries = computed(() => [
  { key: '$context', kind: 'context', label: '' },
  ...fields.value.filter((field) => !enabled.value || common.value.includes(field.key)).map((field) => ({ ...field, kind: 'field' })),
  { key: '$commands', kind: 'commands', label: '' },
  { key: '$divider', kind: 'divider', label: '' },
  ...advanced.value.map((field) => ({ ...field, kind: 'advanced' })),
])
watchEffect(() => {
  if (runtimeMeta) runtimeMeta[definition.value.slotId] = { searchFields: fields.value, fieldApplicability: { commonFields: { enabled: enabled.value, reason: '可用搜索条件不足三个' } } }
})
watch(() => advanced.value.find(field => props.states[field.key].error)?.key, (key) => {
  if (key) expanded.value = true
}, { immediate: true })
onBeforeUnmount(() => { if (runtimeMeta) delete runtimeMeta[definition.value.slotId] })

async function focusField(key: string): Promise<void> {
  expanded.value = true
  await nextTick()
  const field = root.value?.querySelector<HTMLElement>(`[data-search-field="${key}"]`)
  field?.scrollIntoView?.({ block: 'nearest' })
  field?.querySelector<HTMLElement>('input,button,[tabindex="0"]')?.focus()
}
function toggle(): void {
  if (expanded.value) {
    const invalid = advanced.value.find((field) => props.states[field.key].error)
    if (invalid) { ElMessage.warning(props.states[invalid.key].error!); void focusField(invalid.key); return }
    root.value?.querySelector<HTMLButtonElement>('[data-search-toggle]')?.focus()
  }
  expanded.value = !expanded.value
}
</script>

<template>
  <div ref="root" class="app-advanced-search app-control-row-scope" :style="row.style.value" :data-control-row="row.size.value" :data-search-group="group" :aria-label="definition.label">
    <AppScrollArea class="app-advanced-search__controls">
      <template v-for="entry in entries" :key="entry.key">
        <slot v-if="entry.kind === 'context'" name="context" />
        <div v-else-if="entry.kind === 'commands'" class="app-advanced-search__commands">
          <el-button v-if="enabled" text :icon="expanded ? ArrowUp : ArrowDown" :aria-expanded="expanded" data-search-toggle @click="toggle">
            {{ expanded ? '收起高级搜索' : '高级搜索' }}{{ summaries.length ? `（${formatNumber(summaries.length, 'count')}）` : '' }}
          </el-button>
          <slot name="commands" />
        </div>
        <div v-else-if="entry.kind === 'divider'" v-show="enabled && expanded" class="app-advanced-search__divider">高级条件</div>
        <div v-else v-show="entry.kind !== 'advanced' || expanded" class="app-advanced-search__field" :data-search-field="entry.key" :aria-label="entry.label">
          <span v-if="states[entry.key]?.selfLabelled === false" class="app-advanced-search__label">{{ entry.label }}</span>
          <slot :name="entry.key" />
          <span v-if="props.states[entry.key]?.error" role="alert" class="app-advanced-search__error">{{ props.states[entry.key].error }}</span>
        </div>
      </template>
    </AppScrollArea>
    <div v-if="!expanded && summaries.length" class="app-advanced-search__summary" aria-label="生效的高级搜索条件">
      <span>高级条件：</span>
      <el-tag type="primary" effect="light" v-for="field in summaries.slice(0, 3)" :key="field.key" :closable="!!states[field.key].clear" @close="states[field.key].clear?.()">
        <el-button text @click="focusField(field.key)">{{ field.label }}：{{ field.text }}</el-button>
      </el-tag>
      <el-button v-if="summaries.length > 3" text @click="expanded = true">其余 {{ formatNumber(summaries.length - 3, 'count') }} 项</el-button>
    </div>
  </div>
</template>

<style scoped>
.app-advanced-search { width: 100%; min-width: 0; }
.app-advanced-search__controls { max-height: 40cqh; --app-scroll-display: flex; --app-scroll-wrap: wrap; --app-scroll-gap: var(--app-density-control-gap); --app-scroll-align: center; padding: var(--app-space-1); }
.app-advanced-search__commands, .app-advanced-search__summary { display: flex; flex-wrap: wrap; align-items: center; gap: var(--app-density-control-gap, var(--app-space-2)); }
.app-advanced-search__commands { flex: 1 1 auto; }
.app-advanced-search__field { display: flex; flex-wrap: wrap; align-items: center; gap: var(--app-space-2); min-width: 0; max-width: 100%; }
.app-advanced-search__field :deep(> *) { max-width: 100%; }
.app-advanced-search__divider { flex-basis: 100%; border-top: 1px solid var(--el-border-color-lighter); padding-top: var(--app-space-2); }
.app-advanced-search__divider, .app-advanced-search__label, .app-advanced-search__summary { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); }
.app-advanced-search__summary { margin-top: var(--app-space-2); padding-inline: var(--app-space-1); }
.app-advanced-search__summary :deep(.el-tag) { max-width: 100%; height: auto; white-space: normal; }
.app-advanced-search__summary :deep(.el-button) { white-space: normal; text-align: left; }
.app-advanced-search__label { flex: 0 0 auto; white-space: nowrap; }
.app-advanced-search__error { flex-basis: 100%; color: var(--app-danger-text); font-size: var(--app-font-size-caption); }
@container app-viewport (max-width: 720px) {
  .app-advanced-search__field { flex-basis: 100%; }
  .app-advanced-search__field :deep(> :not(.app-advanced-search__label):not(.app-advanced-search__error)) { flex: 1; width: 0; min-width: 0; }
}
</style>
