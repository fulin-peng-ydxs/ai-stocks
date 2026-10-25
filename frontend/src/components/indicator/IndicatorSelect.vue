<script setup lang="ts">
import AppSelect from '@/components/AppSelect.vue'
import { computed } from 'vue'
import type { IndicatorDef } from '@/api/scoreProfile'

defineOptions({ inheritAttrs: false })
const props = defineProps<{
  modelValue?: string
  definitions: IndicatorDef[]
  disabled?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: string]; change: [value: string] }>()

const available = computed(() => props.definitions.filter((item) => item.enabled || item.key === props.modelValue))
const general = computed(() => available.value.filter((item) => item.layer !== 'preset'))
const presets = computed(() => available.value.filter((item) => item.layer === 'preset'))
function update(value: string): void {
  emit('update:modelValue', value)
  emit('change', value)
}
</script>

<template>
  <AppSelect
    v-bind="$attrs"
    :model-value="modelValue || ''"
    :disabled="disabled"
    filterable
    class="indicator-select"
    @update:model-value="update"
    popper-class="app-option-popper indicator-select-popper"
    width="long"
  >
    <el-option-group label="通用指标">
      <el-option v-for="item in general" :key="item.key" :value="item.key" :label="item.name_cn">
        <span class="app-option-label">{{ item.name_cn }}</span>
        <small v-if="!item.enabled" class="app-option-meta">已停用·历史兼容</small>
      </el-option>
    </el-option-group>
    <el-option-group v-if="presets.length" label="快捷预设">
      <el-option v-for="item in presets" :key="item.key" :value="item.key" :label="item.name_cn" />
    </el-option-group>
  </AppSelect>
</template>
