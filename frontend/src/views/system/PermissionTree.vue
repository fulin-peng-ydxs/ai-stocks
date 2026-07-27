<script setup lang="ts">
import { computed, ref } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import PermissionResourceList from './PermissionResourceList.vue'
import type { PermNode } from './permissionTree'

const props = defineProps<{
  node: PermNode
  stateOf: (node: PermNode) => 'on' | 'half' | 'off'
  toggle: (node: PermNode) => void
  readonly: boolean
}>()

const collapsed = ref(props.node.sysLocked)
const resourcesOpen = ref(false)
const childMenus = computed(() => (props.node.children ?? []).filter((child) => child.kind === 'menu'))
const childResources = computed(() => (props.node.children ?? []).filter((child) => child.kind === 'resource'))
const isGroup = computed(() => props.node.nodeType === 'group')
const domKey = computed(() => encodeURIComponent(props.node.key).replaceAll('%', '-'))
const groupToggleId = computed(() => `permission-group-toggle-${domKey.value}`)
const groupRegionId = computed(() => `permission-group-region-${domKey.value}`)
const resourceToggleId = computed(() => `permission-resource-toggle-${domKey.value}`)
const resourceRegionId = computed(() => `permission-resource-region-${domKey.value}`)

function descendantResources(node: PermNode): PermNode[] {
  if (node.kind === 'resource') return [node]
  return (node.children ?? []).flatMap(descendantResources)
}

const resourceStats = computed(() => {
  const resources = descendantResources(props.node)
  const selected = resources.filter((resource) => (
    resource.baselineLocked || props.stateOf(resource) === 'on'
  )).length
  return { selected, total: resources.length }
})
</script>

<template>
  <section v-if="isGroup" class="pt-group" :class="{ collapsed, locked: node.sysLocked }">
    <div class="pt-group-head">
      <el-checkbox
        class="pt-node-checkbox"
        :model-value="stateOf(node) === 'on'"
        :indeterminate="stateOf(node) === 'half'"
        :disabled="readonly || node.sysLocked"
        :aria-label="`选择${node.label}全部权限`"
        @change="toggle(node)"
      />
      <button
        :id="groupToggleId"
        class="pt-group-toggle"
        type="button"
        :aria-expanded="!collapsed"
        :aria-controls="groupRegionId"
        @click="collapsed = !collapsed"
      >
        <el-icon class="pt-caret"><ArrowDown /></el-icon>
        <span class="pt-group-title">{{ node.label }}</span>
        <span v-if="resourceStats.total" class="pt-summary">
          已选 {{ resourceStats.selected }}/{{ resourceStats.total }}
        </span>
        <span v-if="node.sysLocked" class="pt-system-only">仅系统管理员</span>
      </button>
    </div>
    <div
      v-show="!collapsed"
      :id="groupRegionId"
      class="pt-group-body"
      role="region"
      :aria-labelledby="groupToggleId"
    >
      <PermissionTree
        v-for="child in childMenus"
        :key="child.key"
        :node="child"
        :state-of="stateOf"
        :toggle="toggle"
        :readonly="readonly"
      />
      <PermissionResourceList
        v-if="childResources.length"
        :resources="childResources"
        :state-of="stateOf"
        :toggle="toggle"
        :readonly="readonly"
      />
    </div>
  </section>

  <section v-else class="pt-menu" :class="{ locked: node.sysLocked }">
    <div class="pt-menu-row">
      <el-checkbox
        class="pt-node-checkbox"
        :model-value="stateOf(node) === 'on'"
        :indeterminate="stateOf(node) === 'half'"
        :disabled="readonly || node.sysLocked"
        :aria-label="`选择${node.label}权限`"
        @change="toggle(node)"
      />
      <span class="pt-menu-label">{{ node.label }}</span>
      <span v-if="node.sysLocked" class="pt-system-only">仅系统管理员</span>
      <el-button
        v-if="childResources.length"
        :id="resourceToggleId"
        class="pt-resource-trigger"
        link
        size="small"
        :aria-expanded="resourcesOpen"
        :aria-controls="resourceRegionId"
        :aria-label="`${node.label}功能权限 ${resourceStats.selected}/${resourceStats.total}`"
        @click="resourcesOpen = !resourcesOpen"
      >
        功能权限 {{ resourceStats.selected }}/{{ resourceStats.total }}
        <el-icon class="pt-resource-caret" :class="{ open: resourcesOpen }"><ArrowDown /></el-icon>
      </el-button>
      <span v-else class="pt-summary">无功能点</span>
    </div>
    <PermissionResourceList
      v-if="childResources.length"
      v-show="resourcesOpen"
      :id="resourceRegionId"
      role="region"
      :aria-labelledby="resourceToggleId"
      :resources="childResources"
      :state-of="stateOf"
      :toggle="toggle"
      :readonly="readonly"
    />
  </section>
</template>

<style scoped>
.pt-group {
  overflow: hidden;
  margin-bottom: var(--app-space-3);
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  background: var(--el-bg-color);
}
.pt-group-head {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  min-height: 40px;
  padding: 7px 12px;
  background: var(--el-fill-color-light);
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-section);
}
.pt-group-toggle {
  display: flex;
  flex: 1 1 auto;
  align-items: center;
  gap: var(--app-space-2);
  min-width: 0;
  padding: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
  text-align: left;
}
.pt-group-toggle:focus-visible {
  border-radius: var(--layout-control-radius);
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
}
.pt-group-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  user-select: none;
  white-space: nowrap;
}
.pt-caret,
.pt-resource-caret {
  color: var(--el-text-color-secondary);
  transition: transform 150ms ease;
}
.pt-group.collapsed .pt-caret {
  transform: rotate(-90deg);
}
.pt-resource-caret {
  margin-left: 3px;
  transform: rotate(-90deg);
}
.pt-resource-caret.open {
  transform: rotate(0);
}
.pt-group-body {
  padding: 4px 12px 8px;
}
.pt-group-body .pt-group {
  margin: var(--app-space-2) 0 var(--app-space-2) var(--app-space-3);
  border-color: var(--el-border-color-lighter);
}
.pt-menu {
  overflow: hidden;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.pt-menu:last-child {
  border-bottom: 0;
}
.pt-menu-row {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  min-height: 40px;
  padding: 6px 8px;
}
.pt-menu-label {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-section);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pt-summary {
  flex: none;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  font-weight: var(--app-font-weight-regular);
}
.pt-group-toggle .pt-summary {
  margin-left: auto;
}
.pt-resource-trigger {
  flex: none;
  margin-left: auto;
  padding: 0 2px;
}
.pt-system-only {
  flex: none;
  padding: 0 4px;
  border: 1px solid color-mix(in srgb, var(--el-color-warning) 40%, var(--el-border-color));
  border-radius: 3px;
  color: var(--el-color-warning);
  font-size: var(--app-font-size-caption);
  font-weight: var(--app-font-weight-regular);
}
.pt-node-checkbox {
  height: auto;
  margin-right: 0;
}
.pt-node-checkbox :deep(.el-checkbox__label) {
  display: none;
}
@media (prefers-reduced-motion: reduce) {
  .pt-caret,
  .pt-resource-caret {
    transition: none;
  }
}
</style>
