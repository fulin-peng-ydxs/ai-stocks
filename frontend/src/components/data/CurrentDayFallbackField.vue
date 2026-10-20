<script setup lang="ts">
import AppFormHelp from '@/components/AppFormHelp.vue'
defineProps<{
  modelValue: boolean
  testId: string
}>()

defineEmits<{ 'update:modelValue': [value: boolean] }>()
</script>

<template>
  <el-form-item label="当日退级">
    <el-checkbox
      :model-value="modelValue"
      :data-testid="testId"
      @update:model-value="$emit('update:modelValue', Boolean($event))"
    >
      强制采集当日
    </el-checkbox>
    <AppFormHelp>仅在当日已收盘后跳过源端就绪回退；休市日及15:30前不可强制</AppFormHelp>
  </el-form-item>
</template>
