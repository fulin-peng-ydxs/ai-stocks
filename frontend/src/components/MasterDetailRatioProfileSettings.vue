<script setup lang="ts">
import PageSettingsApplyButton from './PageSettingsApplyButton.vue'
import {
  upsertMasterDetailRatioProfile,
  type MasterDetailRatioProfilesConfig,
  type MasterDetailRatioSample,
} from '@/layout/masterDetailRatioProfiles'

const props = defineProps<{
  modelValue?: unknown
  currentSample?: MasterDetailRatioSample
}>()

const emit = defineEmits<{
  apply: [value: { profiles: MasterDetailRatioProfilesConfig; ratio: number }]
}>()

function saveCurrent(): void {
  if (!props.currentSample) return
  emit('apply', {
    profiles: upsertMasterDetailRatioProfile(props.modelValue, props.currentSample),
    ratio: props.currentSample.ratio,
  })
}
</script>

<template>
  <PageSettingsApplyButton
    :disabled="!currentSample"
    label="使用页面当前比例"
    test-id="master-ratio-profile-save-current"
    @click="saveCurrent"
  />
</template>
