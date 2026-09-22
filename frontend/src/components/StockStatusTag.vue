<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  isSt?: boolean | null
  asOfDate?: string | null
  contextLabel?: string
  showUnknown?: boolean
  /** 上层已明确限定为纯 ST 集合时隐藏重复身份信息。 */
  stOnlyContext?: boolean
}>(), {
  isSt: null,
  asOfDate: null,
  contextLabel: '截至',
  showUnknown: false,
  stOnlyContext: false,
})

const visible = computed(() => !props.stOnlyContext
  && (props.isSt === true || (props.isSt == null && props.showUnknown)))
const title = computed(() => {
  const point = props.asOfDate ? `${props.contextLabel} ${props.asOfDate}，` : ''
  return props.isSt === true
    ? `${point}该股票处于 ST 状态`
    : `${point}该股票的 ST 状态未知`
})
</script>

<template>
  <span v-if="visible" class="stock-status-tag-shell" :title="title" :aria-label="title">
    <el-tag
      class="stock-status-tag"
      :type="isSt === true ? 'danger' : 'info'"
      size="small"
      effect="plain"
    >{{ isSt === true ? 'ST' : 'ST状态未知' }}</el-tag>
  </span>
</template>

<style scoped>
.stock-status-tag-shell {
  display: inline-flex;
  flex: none;
  align-items: center;
  line-height: var(--app-line-height-solid);
}
</style>
