// @vitest-environment jsdom

import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'

import IndicatorParamFields from '../IndicatorParamFields.vue'
import IndicatorParamSchemaEditor from '../IndicatorParamSchemaEditor.vue'
import IndicatorSelect from '../IndicatorSelect.vue'
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
