// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { defineComponent, reactive } from 'vue'
import { ElForm, ElFormItem, ElInput, ElOption, ElSelect } from 'element-plus'
import { describe, expect, it } from 'vitest'
import AppForm from '../AppForm.vue'
import PageSegmented from '../PageSegmented.vue'
import AppFilterSelect from '../AppFilterSelect.vue'

describe('一级编辑表单尺寸', () => {
  it.each([false, true])('复合选择器（multiple=%s）的最终控件继承表单尺寸，显式覆盖仍有效', async (multiple) => {
    const wrapper = mount(defineComponent({
      components: { AppForm, ElFormItem, AppFilterSelect },
      props: ['formSize', 'override', 'multiple'],
      setup() { return { selection: reactive({ value: multiple ? [] : '' }) } },
      template: `<AppForm :size="formSize"><ElFormItem label="分类">
        <AppFilterSelect v-model="selection.value" :multiple="multiple" :size="override"
          :options="[{label:'分类 A',value:'a'}]" />
      </ElFormItem></AppForm>`,
    }), {
      props: { formSize: 'large', multiple },
      global: { components: { ElSelect, ElOption } },
    })
    const select = wrapper.getComponent(ElSelect)
    const filter = wrapper.getComponent(AppFilterSelect)
    expect(select.props('size')).toBe('large')
    expect(select.classes()).toContain('el-select--large')
    expect(filter.classes()).toContain('app-filter-select--large')
    await wrapper.setProps({ formSize: 'small' })
    expect(select.props('size')).toBe('small')
    expect(filter.classes()).toContain('app-filter-select--small')
    await wrapper.setProps({ override: 'default' })
    expect(select.props('size')).toBe('default')
    expect(filter.classes()).toContain('app-filter-select--default')
    wrapper.unmount()
  })

  it('主表单的输入框和嵌套分段默认跟随页面密度，并保留字段写回', async () => {
    const wrapper = mount(defineComponent({
      components: { AppForm, ElFormItem, ElInput, PageSegmented },
      setup() { return { draft: reactive({ name: '', mode: 'all' }) } },
      template: `<AppForm label-width="80px"><ElFormItem label="名称"><ElInput v-model="draft.name" /></ElFormItem>
        <div><PageSegmented v-model="draft.mode" :options="[{label:'全部',value:'all'},{label:'指定',value:'selected'}]" /></div>
      </AppForm>`,
    }))
    expect(wrapper.getComponent(ElForm).props('size')).toBe('default')
    expect(wrapper.getComponent(ElInput).classes()).not.toContain('el-input--large')
    expect(wrapper.getComponent(PageSegmented).classes()).not.toContain('page-segmented--large')
    await wrapper.get('input').setValue('采集任务')
    await wrapper.getComponent(PageSegmented).findAll('button')[1].trigger('click')
    expect(wrapper.vm.draft).toEqual({ name: '采集任务', mode: 'selected' })
    wrapper.unmount()
  })

  it('独立场景可显式声明尺寸', async () => {
    const wrapper = mount(AppForm, { props: { size: 'large' } })
    expect(wrapper.getComponent(ElForm).props('size')).toBe('large')
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
