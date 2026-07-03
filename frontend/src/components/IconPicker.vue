<script setup lang="ts">
// 图标选择器（多租户 RBAC stage3·T13）：消费 @element-plus/icons-vue，供菜单 icon 字段选图标名。
// icon 字段存图标名（如 TrendCharts），渲染时按名取组件；不手填字符，从图标库可搜索网格中选。
// 复用组件：SideMenu/菜单管理页共用同一图标名 → 组件映射，保证选什么就渲染什么。
import { computed, ref } from 'vue'
import * as EpIcons from '@element-plus/icons-vue'
import { ArrowDown } from '@element-plus/icons-vue'
import type { Component } from 'vue'

const props = defineProps<{
  modelValue: string | null
  disabled?: boolean
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: string | null): void }>()

// 全部图标名（稳定排序，便于网格展示）
const ALL_NAMES = Object.keys(EpIcons).sort()
const iconMap = EpIcons as unknown as Record<string, Component>

const keyword = ref('')
const visible = ref(false)
const filtered = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return ALL_NAMES
  return ALL_NAMES.filter((n) => n.toLowerCase().includes(q))
})

const currentComp = computed<Component | null>(() =>
  props.modelValue ? (iconMap[props.modelValue] ?? null) : null,
)

function choose(name: string) {
  emit('update:modelValue', name)
  visible.value = false
}
function clear() {
  emit('update:modelValue', null)
  visible.value = false
}
</script>

<template>
  <el-popover
    v-model:visible="visible"
    :width="300"
    trigger="click"
    placement="bottom-start"
    :disabled="disabled"
    popper-class="icon-picker-pop"
  >
    <template #reference>
      <div class="ip-trigger" :class="{ disabled }">
        <span class="ip-cur">
          <el-icon v-if="currentComp" :size="16"><component :is="currentComp" /></el-icon>
          <span class="ip-name">{{ modelValue || '选择图标' }}</span>
        </span>
        <el-icon class="ip-chev"><ArrowDown /></el-icon>
      </div>
    </template>

    <div class="ip-panel">
      <el-input
        v-model="keyword"
        size="small"
        placeholder="搜索图标名（Element Plus Icons）"
        clearable
      />
      <div class="ip-actions">
        <span class="ip-count">{{ filtered.length }} 个</span>
        <el-button link size="small" @click="clear">清除图标</el-button>
      </div>
      <div class="ip-grid">
        <div
          v-for="name in filtered"
          :key="name"
          class="ip-cell"
          :class="{ on: name === modelValue }"
          :title="name"
          @click="choose(name)"
        >
          <el-icon :size="18"><component :is="iconMap[name]" /></el-icon>
          <span class="ip-cap">{{ name }}</span>
        </div>
        <div v-if="!filtered.length" class="ip-empty">无匹配图标</div>
      </div>
    </div>
  </el-popover>
</template>

<style scoped>
.ip-trigger {
  height: 32px; width: 100%; border: 1px solid var(--el-border-color); border-radius: 4px;
  background: var(--el-bg-color); color: var(--el-text-color-primary); padding: 0 8px;
  display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px;
}
.ip-trigger:hover:not(.disabled) { border-color: var(--el-color-primary); }
.ip-trigger.disabled { cursor: not-allowed; background: var(--el-disabled-bg-color); color: var(--el-text-color-placeholder); }
.ip-cur { display: inline-flex; align-items: center; gap: 6px; min-width: 0; }
.ip-name { font-family: ui-monospace, Menlo, monospace; font-size: 12px; color: var(--el-text-color-regular);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ip-chev { margin-left: auto; color: var(--el-text-color-secondary); }
.ip-panel { display: flex; flex-direction: column; gap: 8px; }
.ip-actions { display: flex; align-items: center; justify-content: space-between; }
.ip-count { font-size: 12px; color: var(--el-text-color-secondary); }
.ip-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 6px; max-height: 200px; overflow: auto; }
.ip-cell { aspect-ratio: 1; border: 1px solid var(--el-border-color-lighter); border-radius: 6px;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 2px;
  cursor: pointer; color: var(--el-text-color-regular); overflow: hidden; }
.ip-cell:hover { background: var(--el-fill-color-light); border-color: var(--el-color-primary); }
.ip-cell.on { background: var(--el-color-primary-light-9); border-color: var(--el-color-primary); color: var(--el-color-primary); }
.ip-cap { font-size: 9px; color: var(--el-text-color-secondary); transform: scale(0.82);
  white-space: nowrap; max-width: 100%; overflow: hidden; text-overflow: ellipsis; }
.ip-empty { grid-column: 1 / -1; text-align: center; padding: 16px; font-size: 12px; color: var(--el-text-color-secondary); }
</style>
