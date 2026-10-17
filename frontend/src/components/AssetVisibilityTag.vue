<script setup lang="ts">
import AppHoverInfo from '@/components/AppHoverInfo'
import { computed, ref } from 'vue'
import SystemBuiltinTag from './SystemBuiltinTag.vue'

type AssetSource = 'mine' | 'tenant' | 'public' | 'preset'
type AssetVisibility = 'private' | 'tenant' | 'public'

const props = withDefaults(defineProps<{
  mode?: 'source' | 'visibility' | 'readonly'
  source?: AssetSource | null
  visibility?: AssetVisibility | null
  ownerLabel?: string | null
  readonly?: boolean
  clickable?: boolean
  labelMine?: string
}>(), {
  mode: 'visibility',
  source: null,
  visibility: 'private',
  ownerLabel: null,
  readonly: false,
  clickable: false,
  labelMine: '我的',
})

const tag = ref<{ $el: HTMLElement }>()
const tagElement = computed(() => tag.value?.$el)

const label = computed(() => {
  if (props.mode === 'readonly') return '只读'
  if (props.mode === 'source') {
    if (props.source === 'preset') return '系统内置'
    if (props.source === 'tenant') return '租户公开'
    if (props.source === 'public') return '全体公开'
    return props.labelMine
  }
  if (props.visibility === 'tenant') return '租户公开'
  if (props.visibility === 'public') return '全体公开'
  return '私有'
})

const tagType = computed(() => {
  if (props.mode === 'readonly') return 'info'
  const value = props.mode === 'source' ? props.source : props.visibility
  if (value === 'tenant') return 'success'
  if (value === 'public') return 'warning'
  if (value === 'preset') return 'info'
  return props.mode === 'source' ? 'primary' : 'info'
})

const tooltipContent = computed(() => {
  const owner = props.ownerLabel ? ` · ${props.ownerLabel}` : ''
  return props.readonly && props.mode !== 'readonly' ? `${label.value}${owner} · 只读` : `${label.value}${owner}`
})
</script>

<template>
  <SystemBuiltinTag v-if="mode === 'source' && source === 'preset'" />
  <el-tag
    v-else
    ref="tag"
    :tabindex="tooltipContent !== label ? 0 : undefined"
    class="asset-visibility-tag"
    :class="{ 'is-clickable': clickable }"
    :type="tagType"
    size="small"
    effect="plain"
  >
    <span class="asset-visibility-tag__text">{{ label }}</span>
    <slot />
    <AppHoverInfo v-if="tooltipContent !== label && tagElement" :reference="tagElement" :content="tooltipContent" />
  </el-tag>
</template>

<style scoped>
.asset-visibility-tag {
  max-width: 112px;
  vertical-align: middle;
}
.asset-visibility-tag.is-clickable {
  cursor: pointer;
  user-select: none;
}
.asset-visibility-tag__text {
  display: inline-block;
  max-width: 82px;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: -3px;
  white-space: nowrap;
}
</style>
