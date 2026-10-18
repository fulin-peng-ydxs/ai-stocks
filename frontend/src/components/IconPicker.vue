<script setup lang="ts">
import AppScrollArea from '@/components/AppScrollArea.vue'
import { vKeyboardActivate } from '@/directives/keyboardActivate'
// 图标选择器（多租户 RBAC stage3·T13）：消费 @element-plus/icons-vue，供菜单 icon 字段选图标名。
// icon 字段存图标名（如 TrendCharts），渲染时按名取组件；不手填字符，从图标库可搜索网格中选。
// 复用组件：SideMenu/菜单管理页共用同一图标名 → 组件映射，保证选什么就渲染什么。
import { computed, ref } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import { MENU_ICON_NAMES, resolveMenuIcon } from '@/utils/menuIcon'

const props = defineProps<{
  modelValue: string | null
  disabled?: boolean
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: string | null): void }>()

// 全部图标名（稳定排序，便于网格展示）
const keyword = ref('')
const visible = ref(false)
const filtered = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return MENU_ICON_NAMES
  return MENU_ICON_NAMES.filter((n) => n.toLowerCase().includes(q))
})

const currentComp = computed(() => resolveMenuIcon(props.modelValue))

function choose(name: string) {
  if (props.disabled) return
  emit('update:modelValue', name)
  visible.value = false
}
function clear() {
  if (props.disabled) return
  emit('update:modelValue', null)
  visible.value = false
}
</script>

<template>
  <el-popover
    v-model:visible="visible"
    :width="420"
    trigger="click"
    role="dialog"
    title="选择图标"
    placement="bottom-start"
    :disabled="disabled"
    popper-class="icon-picker-pop"
  >
    <template #reference>
      <div class="ip-trigger app-focus-ring" :class="{ disabled }"
           role="button" :tabindex="disabled ? -1 : 0" :aria-disabled="disabled"
           aria-label="选择图标">
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
        <el-button link size="small" :disabled="disabled" @click="clear">清除图标</el-button>
      </div>
      <AppScrollArea class="ip-grid">
        <div
          v-for="name in filtered"
          :key="name"
          class="ip-cell app-interaction-list-item"
          role="button" :tabindex="disabled ? -1 : 0" :aria-disabled="disabled"
          :aria-label="name" :aria-pressed="name === modelValue"
          v-keyboard-activate
          :class="{ on: name === modelValue }"
          @click="choose(name)"
        >
          <el-icon :size="18"><component :is="resolveMenuIcon(name)" /></el-icon>
          <span class="ip-cap">{{ name }}</span>
        </div>
        <div v-if="!filtered.length" class="app-empty-inline ip-empty">无匹配图标</div>
      </AppScrollArea>
    </div>
  </el-popover>
</template>

<style scoped>
.ip-trigger {
  height: 32px; width: 100%; border: 1px solid var(--el-border-color); border-radius: 4px;
  background: var(--el-bg-color); color: var(--el-text-color-primary); padding: 0 8px;
  display: flex; align-items: center; gap: var(--app-space-2); cursor: pointer; font-size: var(--app-font-size-table);
}
@media (hover: hover) and (pointer: fine) {
.ip-trigger:hover:not(.disabled) { border-color: var(--el-color-primary); }
}
.ip-trigger.disabled { cursor: not-allowed; background: var(--el-disabled-bg-color); color: var(--el-text-color-placeholder); }
.ip-cur { display: inline-flex; align-items: center; gap: var(--app-space-control-gap); min-width: 0; }
.ip-name { font-family: var(--app-font-family-mono); font-size: var(--app-font-size-caption); color: var(--el-text-color-regular);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ip-chev { margin-left: auto; color: var(--el-text-color-secondary); }
.ip-panel { display: flex; flex-direction: column; gap: var(--app-space-2); }
.ip-actions { display: flex; align-items: center; justify-content: space-between; }
.ip-count { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); }
.ip-grid { --app-scroll-display: grid; --app-scroll-columns: repeat(4, minmax(0, 1fr)); --app-scroll-gap: var(--app-space-2); max-height: 320px; }
.ip-cell { height: 58px; min-width: 0; border: 1px solid var(--el-border-color-lighter); border-radius: 6px;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--app-space-1);
  cursor: pointer; color: var(--el-text-color-regular); overflow: hidden; }
.ip-cell.on { border-color: var(--el-color-primary); color: var(--el-color-primary); }
.ip-cap { display: block; width: 100%; padding: 0 4px; font-size: var(--app-font-size-caption); line-height: var(--app-line-height-caption);
  color: var(--el-text-color-secondary); text-align: center; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ip-empty { grid-column: 1 / -1; min-height: 72px; }

:global(.icon-picker-pop) {
  max-width: calc(100cqw - 32px);
}
</style>
