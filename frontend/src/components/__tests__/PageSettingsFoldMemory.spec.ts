// @vitest-environment jsdom
import { h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import SettingsGroup from '@/components/SettingsGroup.vue'
import LayoutSettingsSection from '@/layout/components/LayoutSettingsSection.vue'
import { clearAuth } from '@/api/authToken'
import { resetDrawerPreferencesForTests, useDrawerPreferences } from '@/composables/useDrawerPreferences'

function mountDrawer(pageKey = 'board', title = '默认查询') {
  return mount(PageSettingsDrawer, {
    props: { modelValue: true, pageKey },
    slots: {
      layout: () => h(LayoutSettingsSection, {
        knobs: [{ path: 'density', groupKey: 'base', group: '基础布局', label: '信息密度', type: 'enum', options: ['standard'] }],
        valueOf: () => 'standard', set: vi.fn(),
      }),
      business: () => h(PageSettingSection, { sectionKey: 'default-query', title }, {
        default: () => h(SettingsGroup, { title: '高级参数', foldKey: 'business:default-query:advanced', level: 3 }, () => '内容'),
      }),
    },
    global: { stubs: {
      PageDrawer: {
        props: ['modelValue'],
        template: '<div v-if="modelValue"><slot name="header-actions"/><slot/><slot name="footer"/></div>',
      },
      PageSegmented: true, SourceTag: true, HelpHint: true, ElIcon: true, ElInputNumber: true,
      ElButton: { template: '<button><slot/></button>' },
    } },
  })
}

function group(wrapper: ReturnType<typeof mountDrawer>, title: string) {
  return wrapper.get(`[data-settings-group-title="${title}"]`)
}
function isOpen(wrapper: ReturnType<typeof mountDrawer>, title: string) {
  return group(wrapper, title).attributes('data-settings-group-open') === 'true'
}
async function toggle(wrapper: ReturnType<typeof mountDrawer>, title: string) {
  await group(wrapper, title).get('.sg-head').trigger('click')
}

describe('页面设置抽屉的多层折叠记忆', () => {
  beforeEach(() => {
    clearAuth()
    localStorage.clear()
    resetDrawerPreferencesForTests()
  })

  it('业务插槽内各层及自动布局分组重建后恢复，改标题不丢失，其他页面不串用', async () => {
    const first = mountDrawer()
    await flushPromises()
    await toggle(first, '基础布局')
    await toggle(first, '高级参数')
    await toggle(first, '默认查询')
    first.unmount()
    // 模拟刷新，清掉运行态单例，只从当前身份的持久化偏好恢复。
    resetDrawerPreferencesForTests()
    const restored = mountDrawer('board', '新的展示名称')
    await flushPromises()
    expect(isOpen(restored, '基础布局')).toBe(false)
    expect(isOpen(restored, '新的展示名称')).toBe(false)
    expect(isOpen(restored, '高级参数')).toBe(false)
    const other = mountDrawer('stocks')
    await flushPromises()
    expect(isOpen(other, '基础布局')).toBe(true)
    expect(isOpen(other, '默认查询')).toBe(true)
    restored.unmount()
    other.unmount()
  })

  it('一级分组全局共享；父级收展只隐藏内容，批量子级操作不改写孙级', async () => {
    const wrapper = mountDrawer()
    await flushPromises()
    await toggle(wrapper, '高级参数')
    await toggle(wrapper, '业务选项')
    const other = mountDrawer('stocks')
    await flushPromises()
    expect(isOpen(other, '业务选项')).toBe(false)
    await toggle(wrapper, '业务选项')
    expect(isOpen(other, '业务选项')).toBe(true)
    expect(isOpen(wrapper, '默认查询')).toBe(true)
    expect(isOpen(wrapper, '高级参数')).toBe(false)
    await wrapper.get('button[aria-label="业务选项：收起下级分组"]').trigger('click')
    expect(isOpen(wrapper, '默认查询')).toBe(false)
    expect(isOpen(wrapper, '高级参数')).toBe(false)
    await wrapper.get('button[aria-label="业务选项：展开下级分组"]').trigger('click')
    expect(isOpen(wrapper, '默认查询')).toBe(true)
    expect(isOpen(wrapper, '高级参数')).toBe(false)
    wrapper.unmount()
    other.unmount()
  })

  it('恢复默认立即重置所有当前页子级，包括隐藏节点；其他页保持记忆', async () => {
    const wrapper = mountDrawer()
    await flushPromises()
    useDrawerPreferences().setGroupOpen('stocks', 'layout:base', false)
    await toggle(wrapper, '基础布局')
    await toggle(wrapper, '高级参数')
    await toggle(wrapper, '默认查询')
    await toggle(wrapper, '业务选项')
    await wrapper.get('button.ps-reset').trigger('click')
    expect(isOpen(wrapper, '基础布局')).toBe(true)
    expect(isOpen(wrapper, '业务选项')).toBe(true)
    expect(isOpen(wrapper, '默认查询')).toBe(true)
    expect(isOpen(wrapper, '高级参数')).toBe(true)
    expect(useDrawerPreferences().groupOpen('stocks', 'layout:base')).toBe(false)
    wrapper.unmount()
  })

  it('没有页面标识的兼容抽屉仍可正常收展，不产生不明确归属的持久化记录', async () => {
    const wrapper = mountDrawer('')
    await flushPromises()
    await toggle(wrapper, '默认查询')
    expect(isOpen(wrapper, '默认查询')).toBe(false)
    wrapper.unmount()
  })
})
