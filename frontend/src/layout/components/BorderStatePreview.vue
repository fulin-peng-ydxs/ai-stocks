<script setup lang="ts">
import { ref } from 'vue'
import { APP_BOTTOM_FLOATING_FALLBACKS, APP_BOTTOM_FLOATING_PLACEMENT } from '@/utils/floatingPlacement'
import AppDatePicker from '@/components/AppDatePicker.vue'
import AppSelect from '@/components/AppSelect.vue'
import AppTableCard from '@/components/AppTableCard.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppDetailFields from '@/components/AppDetailFields.vue'
import AppDetailField from '@/components/AppDetailField.vue'
import AppStatusNotice from '@/components/AppStatusNotice.vue'
import PageSegmented from '@/components/PageSegmented.vue'

// 样板只改变本地展示状态，使用真实组件，不请求或保存业务数据。
const disabled = ref(false)
const invalid = ref(false)
const value = ref('示例内容')
const range = ref<[string, string]>(['2026-01-01', '2026-01-02'])
const selection = ref('a')
const number = ref(2)
const color = ref('#1677ff')
const columns = ref<1 | 2 | 3>(2)
const state = ref<'loading' | 'empty' | 'error'>('empty')
const options = [{ label: '方案一', value: 'a' }, { label: '方案二', value: 'b' }]
</script>

<template>
  <details class="border-state-preview">
    <summary class="app-section-title">真实组件边界状态样板</summary>
    <p class="app-caption-text">本地样板，可用 Tab 核对焦点；跟随当前主题与圆角，不保存业务数据。</p>
    <div class="border-state-preview__tools">
      <el-checkbox v-model="disabled">禁用控件</el-checkbox>
      <el-checkbox v-model="invalid">字段错误</el-checkbox>
      <el-radio-group v-model="columns" aria-label="详情列数">
        <el-radio-button :value="1">一列</el-radio-button>
        <el-radio-button :value="2">两列</el-radio-button>
        <el-radio-button :value="3">三列</el-radio-button>
      </el-radio-group>
    </div>
    <el-form label-position="top" :disabled="disabled" class="border-state-preview__inputs">
      <el-form-item label="单行输入样板" :error="invalid ? '示例字段错误' : ''">
        <el-input v-model="value" aria-label="单行输入样板" />
      </el-form-item>
      <el-form-item label="文本域样板" :error="invalid ? '示例字段错误' : ''">
        <el-input v-model="value" type="textarea" aria-label="文本域样板" />
      </el-form-item>
      <el-form-item label="范围日期样板" :error="invalid ? '示例字段错误' : ''">
        <AppDatePicker v-model="range" type="daterange" value-format="YYYY-MM-DD"
          start-placeholder="样板开始日期" end-placeholder="样板结束日期" />
      </el-form-item>
      <el-form-item label="选择器样板" :error="invalid ? '示例字段错误' : ''">
        <AppSelect v-model="selection" aria-label="选择器样板">
          <el-option v-for="option in options" :key="option.value" :label="option.label" :value="option.value" />
        </AppSelect>
      </el-form-item>
      <el-form-item label="数字样板"><el-input-number v-model="number" aria-label="数字样板" /></el-form-item>
      <el-form-item label="颜色样板"><el-color-picker v-model="color" aria-label="颜色样板" /></el-form-item>
    </el-form>
    <div class="border-state-preview__tools">
      <PageSegmented v-model="selection" :options="options" :disabled="disabled" aria-label="分段选择样板" />
      <el-segmented v-model="selection" :options="options" :disabled="disabled" aria-label="库分段样板" />
      <el-button :disabled="disabled">普通命令样板</el-button>
      <el-button type="primary" loading>加载命令样板</el-button>
      <el-popover :placement="APP_BOTTOM_FLOATING_PLACEMENT" :fallback-placements="APP_BOTTOM_FLOATING_FALLBACKS" trigger="click" effect="dark" content="浮层形态由内容角色决定，深浅底色不改变卡片圆角。">
        <template #reference><el-button>深底浮层样板</el-button></template>
      </el-popover>
    </div>
    <AppDetailFields :columns="columns">
      <AppDetailField label="字段一" value="普通字段" />
      <AppDetailField label="跨列字段" span="full" value="跨列前存在不完整行，空白区域保持内容面。" />
      <AppDetailField label="字段三" value="普通字段" />
      <AppDetailField label="字段四" />
      <AppDetailField label="字段五" value="普通字段" />
      <AppDetailField label="字段六" value="不完整末行" />
    </AppDetailFields>
    <AppStatusNotice tone="warning" title="软提示边界样板" />
    <div class="border-state-preview__tools">
      <el-radio-group v-model="state" aria-label="结果区域状态">
        <el-radio-button value="loading">加载</el-radio-button>
        <el-radio-button value="empty">空</el-radio-button>
        <el-radio-button value="error">错误</el-radio-button>
      </el-radio-group>
    </div>
    <AppTableCard><AppStateBlock :state="state" title="结果区域样板" size="compact" /></AppTableCard>
  </details>
</template>

<style scoped>
.border-state-preview { min-width: 0; }
.border-state-preview summary { cursor: pointer; }
.border-state-preview summary:focus-visible { outline: var(--app-focus-ring); }
.border-state-preview[open] { display: grid; gap: var(--app-space-3); }
.border-state-preview p { margin: 0; }
.border-state-preview__tools { display: flex; align-items: center; flex-wrap: wrap; gap: var(--app-space-3); }
.border-state-preview__inputs { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr)); gap: var(--app-space-3); }
.border-state-preview__inputs :deep(.el-form-item) { margin-bottom: 0; min-width: 0; }
.border-state-preview__inputs :deep(.el-date-editor) { max-width: 100%; }
</style>
