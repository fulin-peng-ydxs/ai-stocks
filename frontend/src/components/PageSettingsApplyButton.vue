<script setup lang="ts">
const props = withDefaults(defineProps<{
  label?: string
  disabled?: boolean
  loading?: boolean
  testId?: string
}>(), {
  label: '使用页面当前值',
  disabled: false,
  loading: false,
})

const emit = defineEmits<{
  click: []
}>()

function handleClick(): void {
  if (props.disabled || props.loading) return
  emit('click')
}
</script>

<template>
  <el-button
    class="page-settings-apply-button"
    type="primary"
    plain
    :disabled="props.disabled"
    :loading="props.loading"
    :data-testid="props.testId"
    @click="handleClick"
  >{{ props.label }}</el-button>
</template>

<style scoped>
.page-settings-apply-button {
  width: 100%;
  min-width: 0;
  margin-left: 0;
}
</style>
