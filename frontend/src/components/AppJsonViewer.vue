<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElTree, type LoadFunction } from 'element-plus'
import AppScrollArea from './AppScrollArea.vue'
import { LONG_DOCUMENT_TABLE_MAX_HEIGHT } from './table/tableSizing'

const props = withDefaults(defineProps<{ source: string; label?: string }>(), { label: '原始数据' })
const revision = ref(0)
watch(() => props.source, () => { revision.value++ })
const parsed = computed(() => {
  try { return { valid: true, value: JSON.parse(props.source) as unknown } }
  catch { return { valid: false, value: null } }
})
interface JsonNode { id: string; key: string; path: string[]; value: unknown; leaf: boolean }
const isContainer = (value: unknown): value is Record<string, unknown> | unknown[] =>
  value !== null && typeof value === 'object'
function item(key: string, value: unknown, path: string[]): JsonNode {
  return { id: JSON.stringify(path), key, path, value,
    leaf: !isContainer(value) || Object.keys(value).length === 0 }
}
// 只在展开时装载下一层，长数组及深层诊断不会一次性生成整棵 DOM。
const load: LoadFunction = (node, resolve) => {
  if (node.level === 0) return resolve([item('根节点', parsed.value.value, [])])
  const data = node.data as JsonNode
  resolve(isContainer(data.value) ? Object.entries(data.value).map(([key, value]) =>
    item(key, value, [...data.path, key])) : [])
}
function valueText(value: unknown): string {
  if (Array.isArray(value)) return `数组 · ${value.length} 项`
  if (isContainer(value)) return `对象 · ${Object.keys(value).length} 个字段`
  return JSON.stringify(value)
}
</script>

<template>
  <AppScrollArea class="app-json-viewer" :style="{ maxHeight: LONG_DOCUMENT_TABLE_MAX_HEIGHT }">
    <ElTree v-if="parsed.valid" :key="revision" lazy :load="load" node-key="id"
      :props="{ label: 'key', isLeaf: 'leaf' }" :default-expanded-keys="['[]']"
      :aria-label="label" :expand-on-click-node="true">
      <template #default="{ data }">
        <span class="app-json-viewer__node">
          <span class="app-json-viewer__key">{{ data.key }}:</span>
          <span class="app-json-viewer__value">{{ valueText(data.value) }}</span>
        </span>
      </template>
    </ElTree>
    <pre v-else class="app-json-viewer__text" :aria-label="label">{{ source || '未记录原始数据' }}</pre>
  </AppScrollArea>
</template>

<style scoped>
.app-json-viewer { min-width: 0; }
.app-json-viewer :deep(.el-tree-node__content) { height: auto; min-height: var(--el-tree-node-content-height); align-items: flex-start; }
.app-json-viewer__node { min-width: 0; padding-block: var(--app-space-1); font-family: var(--app-font-family-mono); font-size: var(--app-font-size-caption); line-height: var(--app-line-height-reading); white-space: pre-wrap; overflow-wrap: anywhere; }
.app-json-viewer__key { color: var(--el-text-color-primary); margin-right: var(--app-space-2); }
.app-json-viewer__value { color: var(--el-text-color-secondary); }
.app-json-viewer__text { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font-family: var(--app-font-family-mono); font-size: var(--app-font-size-caption); line-height: var(--app-line-height-reading); }
</style>
