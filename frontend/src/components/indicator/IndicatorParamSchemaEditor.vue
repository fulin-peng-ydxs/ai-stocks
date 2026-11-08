<script setup lang="ts">
import AppSelect from '@/components/AppSelect.vue'
import { Plus, Close } from '@element-plus/icons-vue'
import AppIconButton from '@/components/AppIconButton.vue'
import type { IndicatorParam } from '@/api/scoreProfile'

const props = defineProps<{ modelValue: IndicatorParam[]; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: IndicatorParam[]] }>()

function update(index: number, patch: Partial<IndicatorParam>): void {
  emit('update:modelValue', props.modelValue.map((item, i) => i === index ? { ...item, ...patch } : item))
}
function add(): void {
  emit('update:modelValue', [...props.modelValue, {
    name: 'window', label: '统计周期', type: 'int', default: 20,
    min: 2, max: 250, unit: '交易日', description: '',
  }])
}
function remove(index: number): void {
  emit('update:modelValue', props.modelValue.filter((_, i) => i !== index))
}
</script>

<template>
  <div class="indicator-param-schema">
    <div v-for="(param, index) in modelValue" :key="index" class="indicator-param-schema__row app-surface app-surface--section">
      <header>
        <div><b>参数 {{ index + 1 }}</b><span>{{ param.label || param.name || '未命名参数' }}</span></div>
        <AppIconButton label="删除参数" size="xs" tone="danger" :disabled="disabled" @click="remove(index)">
          <el-icon><Close /></el-icon>
        </AppIconButton>
      </header>
      <div class="indicator-param-schema__grid">
        <label><span>英文参数名</span><el-input :model-value="param.name" :disabled="disabled" placeholder="如 window" @update:model-value="(v: string) => update(index, { name: v })" /></label>
        <label><span>页面名称</span><el-input :model-value="param.label" :disabled="disabled" placeholder="如 统计周期" @update:model-value="(v: string) => update(index, { label: v })" /></label>
        <label>
          <span>数值类型</span>
          <AppSelect
            :model-value="param.type"
            :disabled="disabled"
            @update:model-value="(v: string) => update(index, { type: v })"
          >
            <el-option value="int" label="整数" />
            <el-option value="float" label="小数" />
          </AppSelect>
        </label>
        <label><span>单位</span><el-input :model-value="param.unit" :disabled="disabled" placeholder="如 交易日" @update:model-value="(v: string) => update(index, { unit: v })" /></label>
        <label><span>默认值</span><el-input-number :model-value="param.default" :disabled="disabled" :controls="false" @update:model-value="(v: number | undefined) => v !== undefined && update(index, { default: v })" /></label>
        <label><span>最小值</span><el-input-number :model-value="param.min" :disabled="disabled" :controls="false" @update:model-value="(v: number | undefined) => update(index, { min: v ?? null })" /></label>
        <label><span>最大值</span><el-input-number :model-value="param.max" :disabled="disabled" :controls="false" @update:model-value="(v: number | undefined) => update(index, { max: v ?? null })" /></label>
        <label class="indicator-param-schema__description"><span>参数说明</span><el-input :model-value="param.description" :disabled="disabled" placeholder="说明参数改变后会影响什么" @update:model-value="(v: string) => update(index, { description: v })" /></label>
      </div>
    </div>
    <el-button text type="primary" size="small" :disabled="disabled" @click="add">
      <template #icon><el-icon><Plus /></el-icon></template>
      新增一个参数
    </el-button>
  </div>
</template>

<style scoped>
.indicator-param-schema { display: flex; flex-direction: column; gap: var(--app-space-3); width: 100%; }
.indicator-param-schema__row {
  padding: var(--app-space-3);
}
.indicator-param-schema__row header { display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--app-space-3); }
.indicator-param-schema__row header div { display: flex; align-items: baseline; gap: var(--app-space-2); }
.indicator-param-schema__row header div > span { color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); }
.indicator-param-schema__grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--app-space-3); }
.indicator-param-schema__grid label { display: grid; min-width: 0; gap: var(--app-space-1); }
.indicator-param-schema__grid label > span { color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); }
.indicator-param-schema__grid :deep(.el-input-number),
.indicator-param-schema__grid :deep(.el-select) { width: 100%; }
.indicator-param-schema__description { grid-column: span 1; }
@container app-viewport (max-width: 760px) {
  .indicator-param-schema__grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
