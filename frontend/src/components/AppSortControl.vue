<script setup lang="ts">
import {
  APP_BOTTOM_FLOATING_PLACEMENT,
  APP_BOTTOM_FLOATING_POPPER_OPTIONS,
} from '@/utils/floatingPlacement'
import { ArrowDown, Check, Sort, SortDown, SortUp } from '@element-plus/icons-vue'
import { computed } from 'vue'
import AppIconButton from '@/components/AppIconButton.vue'

export interface AppSortControlOption {
  value: string
  label: string
}

type SortOrder = 'asc' | 'desc'

const props = withDefaults(defineProps<{
  modelValue: string
  order: SortOrder
  options: AppSortControlOption[]
  label?: string
  ariaLabel?: string
  testId?: string
  disabled?: boolean
}>(), {
  label: '排序',
  ariaLabel: '排序',
  testId: undefined,
  disabled: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:order': [order: SortOrder]
}>()

const currentLabel = computed(() => (
  props.options.find((option) => option.value === props.modelValue)?.label
  ?? props.options[0]?.label
  ?? '未设置'
))
const nextOrder = computed<SortOrder>(() => (props.order === 'desc' ? 'asc' : 'desc'))
const orderActionLabel = computed(() => `切换为${nextOrder.value === 'asc' ? '升序' : '降序'}`)

function updateSort(value: unknown): void {
  const normalized = String(value)
  if (props.options.some((option) => option.value === normalized)) {
    emit('update:modelValue', normalized)
  }
}
</script>

<template>
  <div class="app-sort-control" :aria-label="ariaLabel">
    <el-dropdown
      trigger="click"
      popper-class="app-command-menu-popper app-sort-control-popper"
      :disabled="disabled"
      @command="updateSort"
      :placement="APP_BOTTOM_FLOATING_PLACEMENT"
      :popper-options="APP_BOTTOM_FLOATING_POPPER_OPTIONS"
    >
      <el-button
        class="app-sort-control__trigger"
        :data-testid="testId"
        :disabled="disabled"
      >
        <el-icon><Sort /></el-icon>
        <span>{{ label }} · {{ currentLabel }}</span>
        <el-icon class="app-sort-control__chevron"><ArrowDown /></el-icon>
      </el-button>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item
            v-for="option in options"
            :key="option.value"
            :command="option.value"
            :class="{ 'is-current': option.value === modelValue }"
          >
            <span>{{ option.label }}</span>
            <el-icon v-if="option.value === modelValue" class="app-sort-control__check">
              <Check />
            </el-icon>
          </el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
    <AppIconButton
      :label="orderActionLabel"
      variant="soft"
      :disabled="disabled"
      :data-testid="testId ? `${testId}-order` : undefined"
      @click="emit('update:order', nextOrder)"
    >
      <SortDown v-if="order === 'desc'" />
      <SortUp v-else />
    </AppIconButton>
  </div>
</template>

<style scoped>
.app-sort-control {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: var(--app-space-1);
  margin-left: auto;
}
.app-sort-control__trigger {
  min-width: var(--app-control-width-short);
  justify-content: flex-start;
}
.app-sort-control__chevron {
  margin-left: auto;
  color: var(--el-text-color-placeholder);
}
.app-sort-control__check {
  margin-left: auto;
  color: var(--el-color-primary);
}
:global(.app-sort-control-popper .el-dropdown-menu__item.is-current) {
  color: var(--el-color-primary);
  font-weight: var(--app-font-weight-section);
}
</style>
