<script setup lang="ts">
import AppForm from '@/components/AppForm.vue'
import AppControlRow from '@/components/AppControlRow.vue'
import AppIconButton from '@/components/AppIconButton.vue'
import AppCloseButton from '@/components/AppCloseButton.vue'
import type { ControlRowSize } from '@/components/controlRowSizing'
import { Refresh } from '@element-plus/icons-vue'
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
const commandLoading = ref(false)
const commandSelected = ref(false)
const value = ref('示例内容')
const range = ref<[string, string]>(['2026-01-01', '2026-01-02'])
const selection = ref('a')
const number = ref(2)
const color = ref('#1677ff')
const columns = ref<1 | 2 | 3>(2)
const state = ref<'loading' | 'empty' | 'error'>('empty')
const options = [{ label: '方案一', value: 'a' }, { label: '方案二', value: 'b' }]
const rowSize = ref<ControlRowSize>('default')
const selections = ref(['a', 'b'])
</script>

<template>
  <details class="border-state-preview">
    <summary class="app-section-title">真实组件边界状态样板</summary>
    <p class="app-caption-text">本地样板，可用 Tab 核对焦点；跟随当前主题与圆角，不保存业务数据。</p>
    <AppControlRow class="border-state-preview__tools">
      <el-checkbox v-model="disabled">禁用控件</el-checkbox>
      <el-checkbox v-model="invalid">字段错误</el-checkbox>
      <el-checkbox v-model="commandLoading">命令加载</el-checkbox>
      <el-radio-group v-model="columns" aria-label="详情列数">
        <el-radio-button :value="1">一列</el-radio-button>
        <el-radio-button :value="2">两列</el-radio-button>
        <el-radio-button :value="3">三列</el-radio-button>
      </el-radio-group>
      <el-radio-group v-model="rowSize" aria-label="操作行尺寸">
        <el-radio-button value="default">跟随密度</el-radio-button>
        <el-radio-button value="small">小号行</el-radio-button>
        <el-radio-button value="large">大号行</el-radio-button>
      </el-radio-group>
    </AppControlRow>
    <AppForm label-position="top" :disabled="disabled" class="border-state-preview__inputs">
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
    </AppForm>
    <AppControlRow :size="rowSize" class="border-state-preview__tools" aria-label="共同高度控件样板">
      <el-input v-model="value" :disabled="disabled" class="app-control-width-short" aria-label="操作行输入样板" />
      <AppSelect v-model="selection" :disabled="disabled" width="short" aria-label="操作行选择样板">
        <el-option v-for="option in options" :key="option.value" :label="option.label" :value="option.value" />
      </AppSelect>
      <AppSelect v-model="selections" multiple collapse-tags :max-collapse-tags="1"
        :disabled="disabled" width="long" aria-label="操作行多选样板">
        <el-option v-for="option in options" :key="option.value" :label="`${option.label} · 较长的候选名称`" :value="option.value" />
      </AppSelect>
      <el-radio-group v-model="selection" :disabled="disabled" aria-label="操作行按钮单选样板">
        <el-radio-button value="a">选项一</el-radio-button><el-radio-button value="b">选项二</el-radio-button>
      </el-radio-group>
      <el-checkbox-group v-model="selections" :disabled="disabled" aria-label="操作行按钮多选样板">
        <el-checkbox-button value="a">甲</el-checkbox-button><el-checkbox-button value="b">乙</el-checkbox-button>
      </el-checkbox-group>
      <AppDatePicker v-model="range" :disabled="disabled" type="daterange" value-format="YYYY-MM-DD"
        class="app-control-width-wide" start-placeholder="开始日期" end-placeholder="结束日期" />
      <el-input-number v-model="number" :disabled="disabled" controls-position="right" class="app-control-width-short" aria-label="操作行数字样板" />
      <PageSegmented v-model="selection" :options="options" :disabled="disabled" aria-label="分段选择样板" />
      <el-segmented v-model="selection" :options="options" :disabled="disabled" aria-label="库分段样板" />
      <el-button :disabled="disabled">普通命令样板</el-button>
      <el-button type="primary" loading>加载命令样板</el-button>
      <AppIconButton label="操作行图标样板" :disabled="disabled"><Refresh /></AppIconButton>
      <el-popover :placement="APP_BOTTOM_FLOATING_PLACEMENT" :fallback-placements="APP_BOTTOM_FLOATING_FALLBACKS" trigger="click" effect="dark" content="浮层形态由内容角色决定，深浅底色不改变卡片圆角。">
        <template #reference><el-button>深底浮层样板</el-button></template>
      </el-popover>
    </AppControlRow>
    <AppControlRow class="border-state-preview__tools" aria-label="无框命令状态样板">
      <el-button text :disabled="disabled" :loading="commandLoading">文字命令样板</el-button>
      <el-button text type="info" :disabled="disabled" :loading="commandLoading">info 文字样板</el-button>
      <el-button text bg :disabled="disabled" :loading="commandLoading">带底文字样板</el-button>
      <el-button link :disabled="disabled" :loading="commandLoading">链接命令样板</el-button>
      <el-button link type="info" :disabled="disabled" :loading="commandLoading">info 链接样板</el-button>
      <el-button text bg type="danger" :disabled="disabled" :loading="commandLoading">危险命令样板</el-button>
      <el-button type="info" :disabled="disabled" :loading="commandLoading">中性有框样板</el-button>
      <AppIconButton label="无框图标样板" :disabled="disabled" :loading="commandLoading"><Refresh /></AppIconButton>
      <AppIconButton label="带底图标样板" variant="soft" :disabled="disabled" :loading="commandLoading"><Refresh /></AppIconButton>
      <AppIconButton label="图标选择样板" :aria-pressed="commandSelected" :disabled="disabled" :loading="commandLoading"
        @click="commandSelected = !commandSelected"><Refresh /></AppIconButton>
      <AppCloseButton label="关闭命令样板" :disabled="disabled" :loading="commandLoading" />
    </AppControlRow>
    <AppDetailFields :columns="columns">
      <AppDetailField label="字段一" value="普通字段" />
      <AppDetailField label="跨列字段" span="full" value="跨列前存在不完整行，空白区域保持内容面。" />
      <AppDetailField label="字段三" value="普通字段" />
      <AppDetailField label="字段四" />
      <AppDetailField label="字段五" value="普通字段" />
      <AppDetailField label="字段六" value="不完整末行" />
    </AppDetailFields>
    <AppStatusNotice tone="warning" title="软提示边界样板" />
    <AppControlRow class="border-state-preview__tools">
      <el-radio-group v-model="state" aria-label="结果区域状态">
        <el-radio-button value="loading">加载</el-radio-button>
        <el-radio-button value="empty">空</el-radio-button>
        <el-radio-button value="error">错误</el-radio-button>
      </el-radio-group>
    </AppControlRow>
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
