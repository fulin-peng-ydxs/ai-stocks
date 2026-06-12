<script setup lang="ts">
// 通用帮助气泡：标题旁一个 ❓，鼠标移入展示规则/注意事项（默认插槽）
defineProps<{ title?: string; width?: number }>()
</script>

<template>
  <el-popover :title="title" :width="width ?? 360" trigger="hover" placement="bottom-start">
    <template #reference>
      <span class="help-icon">?</span>
    </template>
    <div class="help-body">
      <slot />
    </div>
  </el-popover>
</template>

<style scoped>
.help-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  margin-left: 6px;
  border-radius: 50%;
  background: #c0c4cc;
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  cursor: help;
  vertical-align: middle;
}
.help-icon:hover {
  background: #409eff;
}
.help-body {
  font-size: 12.5px;
  line-height: 1.7;
  color: #5a6371;
}
</style>
