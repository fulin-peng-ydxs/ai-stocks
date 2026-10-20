<script setup lang="ts">
defineProps<{
  modelValue: boolean
  testId: string
}>()

defineEmits<{ 'update:modelValue': [value: boolean] }>()
</script>

<template>
  <el-form-item label="当日退级">
    <div class="app-inline-info">
      <el-checkbox
        :model-value="modelValue"
        :data-testid="testId"
        @update:model-value="$emit('update:modelValue', Boolean($event))"
      >
        强制采集当日
      </el-checkbox>
      <span class="app-caption-text">仅在当日已收盘后跳过源端就绪回退；休市日及15:30前不可强制</span>
    </div>
  </el-form-item>
</template>
