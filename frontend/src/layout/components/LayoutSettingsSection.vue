<script setup lang="ts">
/**
 * 布局自定义表单（M3）：由 PageLayout.editable 白名单**自动**渲染控件，
 * 每个旋钮按 type 选控件（enum→分段器 / bool→开关 / int·number→数字输入）。
 * 取值/写值经 useLayoutConfig 的 valueOf/set（set 内含取值域守门）。复用既有设置面板组件，风格统一。
 */
import type { EditableKnob } from '../schema'
import type { LayoutConfigLayer } from '../merge'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingItem from '@/components/PageSettingItem.vue'
import PageToggleRow from '@/components/PageToggleRow.vue'
import SourceTag from '@/components/SourceTag.vue'

const props = defineProps<{
  knobs: EditableKnob[]
  valueOf: (path: string) => unknown
  sourceOf?: (path: string) => LayoutConfigLayer
  layerValuesOf?: (path: string) => Partial<Record<LayoutConfigLayer, unknown>>
  set: (path: string, value: unknown) => void
}>()

function segOptions(knob: EditableKnob) {
  return (knob.options ?? []).map((o) => ({ label: knob.optionLabels?.[String(o)] ?? String(o), value: o }))
}

function sourceOf(path: string): LayoutConfigLayer {
  return props.sourceOf?.(path) ?? 'default'
}
</script>

<template>
  <template v-for="knob in props.knobs" :key="knob.path">
    <PageToggleRow
      v-if="knob.type === 'bool'"
      :label="knob.label"
      :model-value="Boolean(props.valueOf(knob.path))"
      @update:model-value="(v) => props.set(knob.path, v)"
    />
    <PageSettingItem v-else :label="knob.label">
      <template #actions>
        <SourceTag :source="sourceOf(knob.path)" :values="props.layerValuesOf?.(knob.path)" />
      </template>
      <PageSegmented
        v-if="knob.type === 'enum'"
        :model-value="props.valueOf(knob.path) as string | number"
        :options="segOptions(knob)"
        :aria-label="knob.label"
        @update:model-value="(v) => props.set(knob.path, v)"
      />
      <el-input-number
        v-else
        :model-value="props.valueOf(knob.path) as number"
        :min="knob.min"
        :max="knob.max"
        :step="knob.type === 'int' ? 10 : undefined"
        controls-position="right"
        @update:model-value="(v: number | undefined) => v != null && props.set(knob.path, v)"
      />
    </PageSettingItem>
  </template>
</template>
