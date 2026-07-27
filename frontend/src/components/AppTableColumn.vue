<script setup lang="ts">
import { computed, useAttrs } from 'vue'
import {
  resolveAdaptiveColumnWidth,
  type AdaptiveColumnRole,
} from '@/components/table/adaptiveColumnWidth'

defineOptions({ inheritAttrs: false })

const props = defineProps<{
  role?: AdaptiveColumnRole
  type?: string
  label?: string
  prop?: string
}>()

const attrs = useAttrs()
const forwardedAttrs = computed(() => {
  const { width: _width, minWidth: _minWidth, 'min-width': _kebabMinWidth, ...rest } = attrs
  return rest
})
const sizing = computed(() => resolveAdaptiveColumnWidth(props))
</script>

<template>
  <el-table-column
    v-bind="forwardedAttrs"
    :type="type"
    :label="label"
    :prop="prop"
    :width="sizing.width"
    :min-width="sizing.minWidth"
  >
    <template
      v-for="(_, slotName) in $slots"
      :key="slotName"
      #[slotName]="scope"
    >
      <slot :name="slotName" v-bind="scope ?? {}" />
    </template>
  </el-table-column>
</template>
