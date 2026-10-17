<script setup lang="ts">
import type { PermNode } from './permissionTree'

defineProps<{
  resources: PermNode[]
  stateOf: (node: PermNode) => 'on' | 'half' | 'off'
  toggle: (node: PermNode) => void
  readonly: boolean
}>()
</script>

<template>
  <div class="pt-resource-list">
    <el-checkbox
      v-for="resource in resources"
      :key="resource.key"
      class="pt-func"
      :class="{ locked: resource.sysLocked, baseline: resource.baselineLocked }"
      :model-value="resource.baselineLocked || stateOf(resource) === 'on'"
      :disabled="readonly || resource.sysLocked || resource.baselineLocked"
      @change="toggle(resource)"
    >
      <span class="pt-resource-copy">
        <span class="pt-fname">{{ resource.label }}</span>
        <span class="pt-fcode">{{ resource.code || resource.key.replace(/^r:/, '') }}</span>
      </span>
      <span class="pt-ftype">{{ resource.nodeType === 'api' ? '接口' : '按钮' }}</span>
      <span v-if="resource.baselineLocked" class="pt-baseline">基线</span>
      <span v-if="resource.sysLocked" class="pt-system-only">仅系统管理员</span>
    </el-checkbox>
  </div>
</template>

<style scoped>
.pt-resource-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: var(--app-space-2);
  padding: var(--app-space-3);
  background: var(--el-fill-color-lighter);
  border-top: 1px solid var(--el-border-color-lighter);
}
.pt-func {
  display: flex;
  width: 100%;
  height: auto;
  align-items: center;
  gap: var(--app-space-2);
  min-width: 0;
  margin-right: 0;
  padding: 7px 9px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--layout-control-radius);
  color: var(--el-text-color-regular);
  cursor: pointer;
}
.pt-func.locked,
.pt-func.baseline {
  cursor: default;
}
.pt-resource-copy {
  display: flex;
  flex: 1 1 auto;
  gap: var(--app-space-1);
  min-width: 0;
  flex-direction: column;
}
.pt-fname {
  overflow: hidden;
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-caption);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pt-fcode {
  overflow: hidden;
  color: var(--el-text-color-secondary);
  font-family: var(--app-font-family-mono);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-caption);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pt-ftype {
  flex: none;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.pt-baseline,
.pt-system-only {
  flex: none;
  padding: 0 4px;
  border: 1px solid var(--el-border-color);
  border-radius: 3px;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.pt-system-only {
  border-color: var(--app-border-warning);
  color: var(--el-color-warning);
}
:deep(.el-checkbox) {
  height: auto;
  margin-right: 0;
}
:deep(.el-checkbox__label) {
  display: flex;
  flex: 1 1 auto;
  align-items: center;
  gap: var(--app-space-2);
  min-width: 0;
  padding-left: 0;
  color: inherit;
}
</style>
