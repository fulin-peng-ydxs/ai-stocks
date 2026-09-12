<script setup lang="ts">
withDefaults(defineProps<{
  label?: string
  disabled?: boolean
  testId?: string
}>(), {
  label: '使用页面当前值',
  disabled: false,
})

const emit = defineEmits<{
  click: []
}>()
</script>

<template>
  <el-button
    class="page-settings-apply-button"
    type="primary"
    plain
    :disabled="disabled"
    :data-testid="testId"
    @click="emit('click')"
  >{{ label }}</el-button>
</template>

<style scoped>
.page-settings-apply-button {
  width: 100%;
  min-width: 0;
  margin-left: 0;
}
</style>
