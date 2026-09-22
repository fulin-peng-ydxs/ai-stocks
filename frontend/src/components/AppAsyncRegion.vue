<script setup lang="ts">
import { computed } from 'vue'
import AppStateBlock from '@/components/AppStateBlock.vue'

type StateSize = 'default' | 'compact' | 'tiny' | 'inline'

const props = withDefaults(defineProps<{
  loading: boolean
  hasContent: boolean
  error?: string
  loadingTitle?: string
  loadingDescription?: string
  errorTitle?: string
  emptyTitle?: string
  emptyDescription?: string
  stateSize?: StateSize
  fill?: boolean
  retry?: boolean
  retryText?: string
}>(), {
  error: '',
  loadingTitle: '正在加载数据…',
  loadingDescription: '',
  errorTitle: '加载失败',
  emptyTitle: '暂无数据',
  emptyDescription: '',
  stateSize: 'default',
  fill: false,
  retry: false,
  retryText: '重试',
})

const emit = defineEmits<{
  retry: []
}>()

const initialLoading = computed(() => props.loading && !props.hasContent)
const refreshLoading = computed(() => props.loading && props.hasContent)
const loadingMode = computed(() => (
  initialLoading.value ? 'initial' : refreshLoading.value ? 'refresh' : 'idle'
))
</script>

<template>
  <div
    class="app-async-region"
    :class="{ 'app-async-region--fill': fill }"
    :aria-busy="loading"
    :data-loading-mode="loadingMode"
    v-loading="refreshLoading"
  >
    <slot v-if="error" name="error">
      <AppStateBlock
        state="error"
        :size="stateSize"
        :title="errorTitle"
        :description="error"
        :retry="retry"
        :retry-text="retryText"
        @retry="emit('retry')"
      />
    </slot>
    <AppStateBlock
      v-else-if="initialLoading"
      state="loading"
      :size="stateSize"
      :title="loadingTitle"
      :description="loadingDescription"
    />
    <slot v-else-if="hasContent" />
    <slot v-else name="empty">
      <AppStateBlock
        state="empty"
        :size="stateSize"
        :title="emptyTitle"
        :description="emptyDescription"
      />
    </slot>
  </div>
</template>

<style scoped>
.app-async-region {
  width: 100%;
  min-width: 0;
  min-height: 0;
}
.app-async-region--fill {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  height: 100%;
}
</style>
