// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import ElementPlus, { ElMessage, ElSelect } from 'element-plus'
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
  it('只展示运行时可用候选、禁止重复，并保存到当前列表的组件用户层', async () => {
    const { wrapper, config, save } = setup()
    const selects = wrapper.findAllComponents(ElSelect)
    expect(selects).toHaveLength(2)
    expect(selects[0].findAllComponents({ name: 'ElOption' }).map(option => option.props('value'))).toEqual(['role', 'status', 'keyword'])
    expect(selects[0].findAllComponents({ name: 'ElOption' }).find(option => option.props('value') === 'keyword')?.props('disabled')).toBe(true)
    selects[0].vm.$emit('change', 'role')
    await flushPromises()
    expect(config.exportUserConfig().values['slots.head.config.commonFields']).toEqual(['role', 'keyword'])
    expect(save).toHaveBeenCalledOnce()
    const reset = wrapper.findAll('button').find(button => button.text() === '恢复常显条件默认')!
    await reset.trigger('click')
    await flushPromises()
    expect(config.exportUserConfig().values['slots.head.config.commonFields']).toBeUndefined()
    expect(config.componentValueOf('head', 'commonFields')).toEqual(['status', 'keyword'])
    wrapper.unmount()
  })

  it('失败保留待保存选择，显示错误并可重试；普通设置不触发查询', async () => {
    const error = vi.spyOn(ElMessage, 'error').mockImplementation(() => ({ close() {} }))
    const save = vi.fn().mockResolvedValueOnce(false).mockResolvedValueOnce(true)
    const { wrapper, config } = setup(save)
    wrapper.findAllComponents(ElSelect)[0].vm.$emit('change', 'role')
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
    expect(wrapper.findComponent(ElSelect).exists()).toBe(false)
    wrapper.unmount()
  })
})
