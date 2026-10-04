// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import ElementPlus, { ElMessage, ElCheckboxGroup, ElCheckbox } from 'element-plus'
import ComponentAutoSettings from '../ComponentAutoSettings.vue'
import { getPageLayout } from '@/layout/pageRegistry'
import { useLayoutConfig } from '@/layout/useLayoutConfig'
import { SEARCH_RUNTIME_META } from '@/layout/searchContext'

function setup(save = vi.fn().mockResolvedValue(true), allowedLayersOf?: () => ('page' | 'user')[]) {
  localStorage.clear()
  const config = useLayoutConfig(getPageLayout('user-manage'))
  const runtime = reactive({ head: { searchFields: [
    { key: 'role', label: '角色' }, { key: 'status', label: '状态' }, { key: 'keyword', label: '关键词' },
  ] } })
  const wrapper = mount(ComponentAutoSettings, {
    props: { pageKey: 'user-manage', slotIds: ['head'], config: { ...config, save }, allowedLayersOf },
    global: {
      plugins: [ElementPlus], provide: { [SEARCH_RUNTIME_META as symbol]: runtime },
      stubs: { SettingsGroup: { template: '<section><slot /></section>' }, SourceTag: true },
    },
  })
  return { wrapper, config, save }
}

describe('常显条件设置闭环', () => {
  it('只展示可用候选，未选满不保存，选满两项自动保存，统一恢复默认', async () => {
    const { wrapper, config, save } = setup()
    const group = wrapper.getComponent(ElCheckboxGroup)
    expect(group.props('max')).toBe(2)
    expect(group.findAllComponents(ElCheckbox).map(option => option.props('value'))).toEqual(['role', 'status', 'keyword'])
    group.vm.$emit('update:modelValue', ['keyword'])
    await flushPromises()
    expect(save).not.toHaveBeenCalled()
    expect(config.componentValueOf('head', 'commonFields')).toEqual(['status', 'keyword'])
    expect(wrapper.text()).toContain('已选 1/2 项')
    group.vm.$emit('update:modelValue', ['keyword', 'role'])
    await flushPromises()
    expect(config.exportUserConfig().values['slots.head.config.commonFields']).toEqual(['keyword', 'role'])
    expect(save).toHaveBeenCalledOnce()
    expect(wrapper.text()).not.toContain('恢复常显条件默认')
    config.resetAll()
    await flushPromises()
    expect(group.props('modelValue')).toEqual(['status', 'keyword'])
    wrapper.unmount()
  })

  it('关闭或恢复默认可丢弃不完整草稿，异常输入不写入配置', async () => {
    const { wrapper, save } = setup()
    const group = wrapper.getComponent(ElCheckboxGroup)
    group.vm.$emit('update:modelValue', ['keyword'])
    await flushPromises()
    wrapper.vm.resetSearchDrafts()
    await flushPromises()
    expect(group.props('modelValue')).toEqual(['status', 'keyword'])
    group.vm.$emit('update:modelValue', ['keyword', 'role', 'status'])
    await flushPromises()
    expect(save).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('失败保留待保存选择，显示错误并可重试；普通设置不触发查询', async () => {
    const error = vi.spyOn(ElMessage, 'error').mockImplementation(() => ({ close() {} }))
    const save = vi.fn().mockResolvedValueOnce(false).mockResolvedValueOnce(true)
    const { wrapper, config } = setup(save)
    wrapper.getComponent(ElCheckboxGroup).vm.$emit('update:modelValue', ['role', 'keyword'])
    await flushPromises()
    expect(error).toHaveBeenCalledWith('保存失败，请稍后重试')
    expect(config.componentValueOf('head', 'commonFields')).toEqual(['role', 'keyword'])
    await wrapper.findAll('button').find(button => button.text() === '保存失败，重试')!.trigger('click')
    await flushPromises()
    expect(save).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).not.toContain('保存失败，重试')
    wrapper.unmount()
    error.mockRestore()
  })

  it('管理员关闭用户层开放策略后不显示个人常显编辑器', () => {
    const { wrapper } = setup(undefined, () => ['page'])
    expect(wrapper.findComponent(ElCheckboxGroup).exists()).toBe(false)
    wrapper.unmount()
  })
})
