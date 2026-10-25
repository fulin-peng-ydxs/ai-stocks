// @vitest-environment jsdom

import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { defineComponent, ref } from 'vue'
import { describe, expect, it } from 'vitest'

import IndicatorParamFields from '../IndicatorParamFields.vue'
import IndicatorParamSchemaEditor from '../IndicatorParamSchemaEditor.vue'
import IndicatorSelect from '../IndicatorSelect.vue'
import AppForm from '@/components/AppForm.vue'
import type { IndicatorDef } from '@/api/scoreProfile'

const definitions: IndicatorDef[] = [
  {
    key: 'ma', name_cn: '移动平均线', dtype: 'number', category: '均线', categories: ['均线'],
    direction: null, params: [], desc: '', enabled: true, kind: 'expr', expression: 'MA(C,{n})',
    is_builtin: true, layer: 'metric', parent_key: null, preset_params: {},
  },
  {
    key: 'ma20', name_cn: 'MA20', dtype: 'number', category: '均线', categories: ['均线'],
    direction: null, params: [], desc: '', enabled: true, kind: 'expr', expression: 'MA(C,20)',
    is_builtin: true, layer: 'preset', parent_key: 'ma', preset_params: { n: 20 },
  },
  {
    key: 'old', name_cn: '历史指标', dtype: 'number', category: '自定义', categories: [],
    direction: null, params: [], desc: '', enabled: false, kind: 'expr', expression: 'C',
    is_builtin: false, layer: 'metric', parent_key: null, preset_params: {},
  },
]

describe('技术指标共享组件', () => {
  it('指标选择和动态参数继承一级表单尺寸，紧凑例外可显式覆盖且保留输入', async () => {
    const formSize = ref<'large' | 'default'>('large')
    const wrapper = mount(defineComponent({
      components: { AppForm, IndicatorSelect, IndicatorParamFields },
      setup: () => ({ formSize, definitions, values: ref({ window: 20 }),
        params: [{ name: 'window', label: '统计周期', type: 'int', default: 20 }] }),
      template: `<AppForm :size="formSize">
        <IndicatorSelect model-value="ma" :definitions="definitions" />
        <IndicatorParamFields v-model="values" :params="params" />
        <IndicatorSelect size="small" model-value="ma" :definitions="definitions" />
        <IndicatorParamFields size="small" v-model="values" :params="params" />
      </AppForm>`,
    }), { global: { plugins: [ElementPlus] } })
    try {
      const fields = wrapper.findAllComponents({ name: 'ElInputNumber' })
      const selects = wrapper.findAllComponents({ name: 'ElSelect' })
      expect(selects[0].classes()).toContain('el-select--large')
      expect(fields[0].classes()).toContain('el-input-number--large')
      expect(selects[1].classes()).toContain('el-select--small')
      expect(fields[1].classes()).toContain('el-input-number--small')
      fields[0].vm.$emit('update:modelValue', 60)
      formSize.value = 'default'
      await wrapper.vm.$nextTick()
      expect(selects[0].classes()).not.toContain('el-select--large')
      expect(fields[0].classes()).not.toContain('el-input-number--large')
      expect(fields[0].props('modelValue')).toBe(60)
      expect(fields[1].classes()).toContain('el-input-number--small')
    } finally { wrapper.unmount() }
  })

  it('选择器按通用指标和快捷预设分组，并保留已选停用指标', () => {
    const wrapper = mount(IndicatorSelect, {
      props: { modelValue: 'old', definitions },
      global: { plugins: [ElementPlus] },
    })
    const groups = wrapper.findAllComponents({ name: 'ElOptionGroup' })
    expect(groups.map((group) => group.props('label'))).toEqual(['通用指标', '快捷预设'])
    expect(wrapper.get('.indicator-select').classes()).toContain('app-control-width-long')
    const options = wrapper.findAllComponents({ name: 'ElOption' })
    expect(options.map((option) => option.props('label'))).toContain('历史指标')
  })

  it('参数值组件显示单位、范围并以不可变对象回传', async () => {
    const wrapper = mount(IndicatorParamFields, {
      props: {
        modelValue: { window: 20 },
        params: [{ name: 'window', label: '统计周期', type: 'int', default: 20,
          min: 2, max: 250, unit: '交易日', description: '回看长度' }],
      },
      global: { plugins: [ElementPlus] },
    })
    expect(wrapper.text()).toContain('统计周期（交易日）')
    const input = wrapper.findComponent({ name: 'ElInputNumber' })
    await input.vm.$emit('update:modelValue', 60)
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([{ window: 60 }])
  })

  it('参数定义按参数卡展示字段含义，避免压成单行字段矩阵', () => {
    const wrapper = mount(IndicatorParamSchemaEditor, {
      props: {
        modelValue: [{ name: 'window', label: '统计周期', type: 'int', default: 20,
          min: 2, max: 250, unit: '交易日', description: '回看长度' }],
      },
      global: { plugins: [ElementPlus] },
    })
    expect(wrapper.findAll('.indicator-param-schema__row')).toHaveLength(1)
    expect(wrapper.text()).toContain('参数 1')
    expect(wrapper.text()).toContain('英文参数名')
    expect(wrapper.text()).toContain('默认值')
    expect(wrapper.text()).toContain('参数说明')
  })
})
