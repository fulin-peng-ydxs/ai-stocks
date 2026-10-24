// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { defineComponent, reactive } from 'vue'
import { ElForm, ElFormItem, ElInput } from 'element-plus'
import { describe, expect, it } from 'vitest'
import AppForm from '../AppForm.vue'
import PageSegmented from '../PageSegmented.vue'

describe('一级编辑表单尺寸', () => {
  it('主表单的输入框和嵌套分段默认继承大号，并保留字段写回', async () => {
    const wrapper = mount(defineComponent({
      components: { AppForm, ElFormItem, ElInput, PageSegmented },
      setup() { return { draft: reactive({ name: '', mode: 'all' }) } },
      template: `<AppForm label-width="80px"><ElFormItem label="名称"><ElInput v-model="draft.name" /></ElFormItem>
        <div><PageSegmented v-model="draft.mode" :options="[{label:'全部',value:'all'},{label:'指定',value:'selected'}]" /></div>
      </AppForm>`,
    }))
    expect(wrapper.getComponent(ElForm).props('size')).toBe('large')
    expect(wrapper.getComponent(ElInput).classes()).toContain('el-input--large')
    expect(wrapper.getComponent(PageSegmented).classes()).toContain('page-segmented--large')
    await wrapper.get('input').setValue('采集任务')
    await wrapper.getComponent(PageSegmented).findAll('button')[1].trigger('click')
    expect(wrapper.vm.draft).toEqual({ name: '采集任务', mode: 'selected' })
    wrapper.unmount()
  })

  it('局部密度例外可显式声明，不影响默认大号的其他实例', async () => {
    const wrapper = mount(AppForm, { props: { size: 'default' } })
    expect(wrapper.getComponent(ElForm).props('size')).toBe('default')
    await wrapper.setProps({ size: 'small' })
    expect(wrapper.getComponent(ElForm).props('size')).toBe('small')
    wrapper.unmount()
  })

  it('透传禁用、模型和校验规则，并提供原生表单实例', () => {
    const wrapper = mount(defineComponent({
      components: { AppForm, ElFormItem, ElInput },
      setup() { return { model: reactive({ name: '' }) } },
      template: `<AppForm :model="model" :rules="{name:[{required:true,message:'请输入名称'}]}" disabled>
        <ElFormItem prop="name"><ElInput v-model="model.name" /></ElFormItem></AppForm>`,
    }))
    const form = wrapper.getComponent(AppForm)
    expect(wrapper.get('input').element.disabled).toBe(true)
    expect(form.getComponent(ElForm).props('model')).toBe(wrapper.vm.model)
    expect(form.getComponent(ElForm).props('rules')).toEqual({ name: [{ required: true, message: '请输入名称' }] })
    expect(form.vm.form!.validate).toBeTypeOf('function')
    wrapper.unmount()
  })
})
