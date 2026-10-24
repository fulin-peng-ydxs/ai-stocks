// @vitest-environment jsdom
import { defineComponent, nextTick, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { ElConfigProvider, ElForm, ElFormItem, ElInput } from 'element-plus'
import AppControlRow from '../AppControlRow.vue'
import AppForm from '../AppForm.vue'
import AppDialog from '../AppDialog.vue'
import PageDrawer from '../PageDrawer.vue'

const components = { AppControlRow, AppForm, AppDialog, PageDrawer,
  ElForm, ElFormItem, ElConfigProvider, ElInput }

describe('操作行共同尺寸', () => {
  it('无显式档位时继承表单项、表单和全局，default 明确回到页面密度', () => {
    const wrapper = mount(defineComponent({
      components,
      template: `<ElConfigProvider size="small">
        <AppControlRow data-testid="global" />
        <ElForm size="large">
          <AppControlRow data-testid="form" />
          <ElFormItem size="small"><AppControlRow data-testid="item" /></ElFormItem>
          <AppControlRow size="default" data-testid="page" />
        </ElForm>
      </ElConfigProvider>`,
    }))
    for (const [id, size] of [['global', 'small'], ['form', 'large'],
      ['item', 'small'], ['page', 'default']]) {
      expect(wrapper.get(`[data-testid="${id}"]`).attributes('data-control-row')).toBe(size)
    }
    expect(wrapper.get('[data-testid="page"]').attributes('style'))
      .toContain('--app-density-control-height')
    wrapper.unmount()
  })

  it('父行尺寸动态传给嵌套行，切换档位保留输入实例和值', async () => {
    const size = ref<'default' | 'small' | 'large'>('small')
    const wrapper = mount(defineComponent({
      components,
      setup: () => ({ size, value: ref('保留草稿') }),
      template: `<AppControlRow :size="size" data-testid="parent">
        <AppControlRow data-testid="child"><ElInput v-model="value" /></AppControlRow>
        <AppControlRow size="default" data-testid="independent" />
      </AppControlRow>`,
    }))
    const input = wrapper.get('input').element
    expect(wrapper.get('[data-testid="child"]').attributes('data-control-row')).toBe('small')
    size.value = 'large'
    await nextTick()
    expect(wrapper.get('[data-testid="child"]').attributes('data-control-row')).toBe('large')
    expect(wrapper.get('[data-testid="child"]').attributes('style'))
      .toContain('--app-control-height-lg')
    expect(wrapper.get('[data-testid="independent"]').attributes('data-control-row')).toBe('default')
    expect(wrapper.get('input').element).toBe(input)
    expect((input as HTMLInputElement).value).toBe('保留草稿')
    wrapper.unmount()
  })

  it('新表单与独立浮层隔离旧行和旧表单，浮层里的新表单仍可正常继承', async () => {
    const wrapper = mount(defineComponent({
      components,
      template: `<ElForm size="large"><AppControlRow size="small">
        <AppForm><AppControlRow data-testid="new-form" /></AppForm>
        <AppDialog :model-value="true" boundary="app">
          <AppControlRow data-testid="dialog" />
          <AppForm><AppControlRow data-testid="dialog-form" /></AppForm>
        </AppDialog>
        <PageDrawer :model-value="true" boundary="app" title="独立设置">
          <AppControlRow data-testid="drawer" />
        </PageDrawer>
      </AppControlRow></ElForm>`,
    }), { global: { stubs: {
      ElDialog: { template: '<section><slot /></section>' },
      ElDrawer: { template: '<section><slot /></section>' },
      AppScrollArea: { template: '<div><slot /></div>' },
    } } })
    await flushPromises()
    for (const [id, size] of [['new-form', 'large'], ['dialog', 'default'],
      ['dialog-form', 'large'], ['drawer', 'default']]) {
      expect(wrapper.get(`[data-testid="${id}"]`).attributes('data-control-row')).toBe(size)
    }
    expect(wrapper.findAll('.app-control-row-boundary').length).toBeGreaterThanOrEqual(4)
    wrapper.unmount()
  })
})
