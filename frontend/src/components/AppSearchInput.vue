<script setup lang="ts">
import { computed, watch } from 'vue'
import { useDebouncedQuery } from '@/composables/useDebouncedQuery'

export interface AppSearchInputProps {
  modelValue: string
  placeholder?: string
  /** 输入防抖间隔（ms）；回车/清空始终立即。默认 300。 */
  debounceMs?: number
  clearable?: boolean
  size?: 'large' | 'default' | 'small'
  maxlength?: number | string
}

const props = withDefaults(defineProps<AppSearchInputProps>(), {
  placeholder: '搜索',
  debounceMs: 300,
  clearable: true,
  size: 'default',
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'search'): void
}>()

const value = computed({
  get: () => props.modelValue,
  set: (next: string) => emit('update:modelValue', next),
})

let pendingValue = props.modelValue
let lastSearchedValue: string | undefined
let lastSearchedAt = 0
watch(() => props.modelValue, (next) => { pendingValue = next })

const query = useDebouncedQuery(() => {
  const now = Date.now()
  if (pendingValue === lastSearchedValue && now - lastSearchedAt <= props.debounceMs) return
  lastSearchedValue = pendingValue
  lastSearchedAt = now
  emit('search')
}, props.debounceMs)

function scheduleQuery(next: string): void {
  pendingValue = next
  query.schedule()
}
</script>

<template>
  <el-input
    v-model="value"
    class="app-search-input"
    :placeholder="placeholder"
    :clearable="clearable"
    :size="size"
    :maxlength="maxlength"
    @input="scheduleQuery"
    @keyup.enter="query.flush"
    @clear="query.flush"
  >
    <template #prefix>
      <span class="app-search-input__icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="14" height="14"><path fill="currentColor" d="M15.5 14h-.79l-.28-.27a6.5 6.5 0 1 0-.7.7l.27.28v.79l5 4.99L20.49 19zm-6 0A4.5 4.5 0 1 1 14 9.5 4.5 4.5 0 0 1 9.5 14z"/></svg>
      </span>
    </template>
  </el-input>
</template>

<style scoped>
.app-search-input {
  width: var(--app-control-inline-width, 100%);
  min-width: 0;
}
.app-search-input__icon {
  display: inline-flex;
  align-items: center;
}
</style>
