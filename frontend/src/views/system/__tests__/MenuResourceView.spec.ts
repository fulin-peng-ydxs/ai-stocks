// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'
import ElementPlus from 'element-plus'
import MenuResourceView from '@/views/system/MenuResourceView.vue'
import AppReorderTree from '@/components/AppReorderTree.vue'
import { useAuthStore } from '@/stores/auth'
import type { MenuNode } from '@/api/menu'

const api = vi.hoisted(() => ({ list: vi.fn(), reorder: vi.fn(), resources: vi.fn() }))
vi.mock('@/api/menu', () => ({
  listMenus: (...args: unknown[]) => api.list(...args),
  reorderMenus: (...args: unknown[]) => api.reorder(...args),
  listResources: (...args: unknown[]) => api.resources(...args),
  createMenu: vi.fn(), updateMenu: vi.fn(), deleteMenu: vi.fn(),
  createResource: vi.fn(), updateResource: vi.fn(), deleteResource: vi.fn(),
}))
vi.mock('@/composables/useRemoteLayoutConfig', () => ({ useRemoteLayoutConfig: () => ({
  effective: {}, knobs: [], isDirty: ref(false), setKnob: vi.fn(), valueOf: vi.fn(), sourceOf: vi.fn(),
  resetAll: vi.fn(), componentValueOf: () => [], setComponentKnob: vi.fn(), componentSourceOf: vi.fn(),
  layerValuesOf: vi.fn(), componentLayerValuesOf: vi.fn(), componentAllowedLayers: {},
}) }))
vi.mock('@/composables/usePageSettings', () => ({ usePageSettings: () => ({ reset: vi.fn() }) }))
const item = (id: string, children: MenuNode[] = []): MenuNode => ({
  id, code: id, title: id, parent_id: null, type: children.length ? 'group' : 'leaf',
  icon: null, route_path: children.length ? null : `/${id}`, sort: 10, visible: 'system', is_builtin: false, children,
})
const initial = () => [item('group', [item('a'), item('b')])]
const reordered = () => [item('group', [item('b'), item('a')])]
const mounted: ReturnType<typeof mount>[] = []
async function setup(role = 'system') {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.role = role
  const refresh = vi.spyOn(auth, 'fetchMe').mockResolvedValue({} as any)
  const wrapper = mount(MenuResourceView, { global: {
    plugins: [pinia, ElementPlus], directives: { permission: {} },
    stubs: {
      LayoutHost: { template: '<div><slot name="action"/><slot name="main"/><slot name="overlays"/></div>' },
      PageSettingsDrawer: true, PageSettingsTrigger: true, HelpTip: true,
      IconPicker: true, AppDataTable: true, AppDialog: true,
    },
  }, attachTo: document.body })
  mounted.push(wrapper)
  await flushPromises()
  return { wrapper, refresh }
}
beforeEach(() => {
  vi.clearAllMocks()
  api.list.mockResolvedValue(initial())
  api.resources.mockResolvedValue([])
  api.reorder.mockResolvedValue({})
})
afterEach(() => { mounted.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })
describe('菜单排序保存闭环', () => {
  it('子组排序不覆盖其他真实菜单的原始排序值，无变化不提交', async () => {
    const fixed = { ...item('untouched'), sort: 987 }
    api.list.mockResolvedValue([fixed, ...initial()])
    const { wrapper } = await setup()
    const tree = wrapper.getComponent({ name: 'AppReorderTree' })
    tree.vm.$emit('reorder', [fixed, ...initial()])
    await flushPromises()
    expect(api.reorder).not.toHaveBeenCalled()
    api.list.mockResolvedValue([fixed, ...reordered()])
    tree.vm.$emit('reorder', [fixed, ...reordered()])
    await flushPromises()
    expect(api.reorder).toHaveBeenCalledWith([
      { id: 'b', sort: 10, parentId: 'group' }, { id: 'a', sort: 20, parentId: 'group' },
    ])
    expect(tree.props('items')[0].sort).toBe(987)
  })
  it('鼠标与键盘共用一次保存入口，仅保存受影响兄弟组的父级及顺序并刷新导航', async () => {
    const { wrapper, refresh } = await setup()
    const tree = wrapper.getComponent({ name: 'AppReorderTree' })
    api.list.mockResolvedValue(reordered())
    await tree.get('[aria-label="拖动排序：a"]').trigger('keydown', { key: ' ' })
    await tree.get('[aria-label="拖动排序：a"]').trigger('keydown', { key: 'End' })
    await tree.get('[aria-label="拖动排序：a"]').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(api.reorder).toHaveBeenCalledWith([
      { id: 'b', sort: 10, parentId: 'group' }, { id: 'a', sort: 20, parentId: 'group' },
    ])
    expect(refresh).toHaveBeenCalledOnce()
    expect(refresh).toHaveBeenCalledWith({ background: true })
    expect(tree.props('busy')).toBe(false)
  })
  it('保存中锁定菜单操作，拒绝重入，失败回滚服务端顺序并保留选中项', async () => {
    let reject!: (error: Error) => void
    api.reorder.mockReturnValue(new Promise((_resolve, fail) => { reject = fail }))
    const { wrapper, refresh } = await setup()
    const tree = wrapper.getComponent({ name: 'AppReorderTree' })
    await tree.vm.$emit('select', 'a')
    await flushPromises()
    tree.vm.$emit('reorder', reordered())
    await flushPromises()
    expect(tree.props('busy')).toBe(true)
    expect(wrapper.get('.mr-right').attributes('inert')).toBeDefined()
    tree.vm.$emit('reorder', initial())
    await flushPromises()
    expect(api.reorder).toHaveBeenCalledOnce()
    reject(new Error('save failed'))
    await flushPromises()
    expect(tree.props('items')[0].children.map((node: MenuNode) => node.id)).toEqual(['a', 'b'])
    expect(tree.props('currentKey')).toBe('a')
    expect(tree.props('busy')).toBe(false)
    expect(refresh).not.toHaveBeenCalled()
  })
  it('未保存菜单属性先锁定排序，不通过重载覆盖编辑内容', async () => {
    const { wrapper } = await setup()
    const field = wrapper.findAll('.mr-field').find(node => node.text().startsWith('标题'))!
    await field.get('input').setValue('尚未保存的标题')
    const tree = wrapper.getComponent({ name: 'AppReorderTree' })
    expect(tree.props('disabled')).toBe(true)
    tree.vm.$emit('reorder', reordered())
    await flushPromises()
    expect(api.reorder).not.toHaveBeenCalled()
    expect(field.get('input').element.value).toBe('尚未保存的标题')
  })
  it('无排序权限时，即使伪造组件移动事件也不发请求', async () => {
    const { wrapper } = await setup('normal')
    const tree = wrapper.getComponent({ name: 'AppReorderTree' })
    expect(tree.props('canReorder')).toBe(false)
    tree.vm.$emit('reorder', reordered())
    await flushPromises()
    expect(api.reorder).not.toHaveBeenCalled()
  })
})
