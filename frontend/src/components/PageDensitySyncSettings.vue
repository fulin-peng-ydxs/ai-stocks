<script setup lang="ts">
import { ref } from 'vue'
import AppControlRow from '@/components/AppControlRow.vue'
import AppControlItem from '@/components/AppControlItem.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import SettingsGroup from '@/components/SettingsGroup.vue'
import AppStatusNotice from '@/components/AppStatusNotice.vue'
import { pageDensitySyncing, unifyPageDensity } from '@/composables/pageDensitySync'
import type { Density } from '@/layout/schema'
import { getErrorMessage } from '@/utils/error'

const selectedDensity = ref<Density>('standard')
const error = ref('')
const result = ref('')
const options = [
  { label: '紧凑', value: 'compact' },
  { label: '标准', value: 'standard' },
  { label: '宽松', value: 'comfortable' },
]

async function applyDensity() {
  if (pageDensitySyncing.value) return
  error.value = ''
  result.value = ''
  const density = selectedDensity.value
  try {
    const count = await unifyPageDensity(density)
    result.value = `已将 ${count} 个页面统一为${options.find((item) => item.value === density)?.label}密度`
  } catch (cause) {
    error.value = getErrorMessage(cause, '密度同步失败，请重试')
  }
}
</script>

<template>
  <SettingsGroup
    title="基础密度"
    hint="将所选密度应用到所有页面，应用后仍可在各页面单独调整。"
    :level="1"
    :collapsible="false"
  >
    <AppControlRow :wrap="false">
      <AppControlItem grow>
        <PageSegmented
          v-model="selectedDensity"
          aria-label="统一页面密度"
          fill
          :options="options"
          :disabled="pageDensitySyncing"
          @update:model-value="result = ''; error = ''"
        />
      </AppControlItem>
      <el-button
        v-permission="'layout:user-config'"
        text
        type="primary"
        :loading="pageDensitySyncing"
        @click="applyDensity"
      >统一应用</el-button>
    </AppControlRow>
    <AppStateBlock v-if="error" state="error" size="inline" :title="error" retry @retry="applyDensity" />
    <AppStatusNotice v-else-if="result" tone="success" size="inline" :title="result" />
  </SettingsGroup>
</template>
