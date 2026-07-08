<script setup lang="ts">
import AssetVisibilityTag from './AssetVisibilityTag.vue'

type AssetSource = 'mine' | 'tenant' | 'public' | 'preset'

withDefaults(defineProps<{
  name: string
  version?: number | null
  source?: AssetSource | null
  isPreset?: boolean
  ownerLabel?: string | null
  readonly?: boolean
  labelMine?: string
}>(), {
  version: null,
  source: null,
  isPreset: false,
  ownerLabel: null,
  readonly: false,
  labelMine: '我的',
})
</script>

<template>
  <span class="asset-profile-label">
    <span class="asset-profile-label__name">{{ name }}</span>
    <span v-if="version != null" class="asset-profile-label__version">v{{ version }}</span>
    <AssetVisibilityTag
      v-if="source"
      mode="source"
      :source="isPreset ? 'preset' : source"
      :owner-label="ownerLabel"
      :readonly="readonly"
      :label-mine="labelMine"
    />
  </span>
</template>

<style scoped>
.asset-profile-label {
  align-items: center;
  display: inline-flex;
  gap: 6px;
  min-width: 0;
  max-width: 100%;
  vertical-align: middle;
}
.asset-profile-label__name {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.asset-profile-label__version {
  color: var(--el-text-color-secondary);
  flex: 0 0 auto;
  font-size: 12px;
  font-weight: 400;
}
</style>
