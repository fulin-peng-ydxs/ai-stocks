<script setup lang="ts">
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
    <span class="hint">开启后，非交易日或数据未就绪也不回退</span>
  </el-form-item>
</template>
