// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { h, nextTick } from 'vue'
import AppReorderTree from '@/components/AppReorderTree.vue'

interface Item { id: string; group: boolean; children: Item[] }
const leaf = (id: string): Item => ({ id, group: false, children: [] })
const data = (): Item[] => [
  { id: 'g1', group: true, children: [leaf('a'), leaf('b')] },
  { id: 'g2', group: true, children: [leaf('c')] },
]
const mounted: ReturnType<typeof mount>[] = []
function setup(overrides = {}) {
  const wrapper = mount(AppReorderTree<Item>, {
    props: { items: data(), itemLabel: item => item.id, canContain: item => item.group, label: '菜单树', currentKey: 'a', canReorder: true, ...overrides },
    slots: { default: ({ item }: { item: Item }) => h('span', item.id) },
    attachTo: document.body,
  })
  mounted.push(wrapper)
  return wrapper
}
const key = (id: string) => `[data-reorder-key="${id}"] .app-drag-handle`
function pointer(type: string, y: number) {
  const event = new Event(type, { bubbles: true, cancelable: true })
  Object.defineProperties(event, { pointerId: { value: 1 }, button: { value: 0 }, clientX: { value: 50 }, clientY: { value: y } })
  return event
}
function geometry(wrapper: ReturnType<typeof setup>) {
  const rect = (top: number, height: number) => ({ top, bottom: top + height, left: 0, right: 300, width: 300, height, x: 0, y: top, toJSON() {} })
  vi.spyOn(wrapper.element, 'getBoundingClientRect').mockReturnValue(rect(0, 240))
  wrapper.findAll('[data-reorder-key]').forEach((row, index) => {
    vi.spyOn(row.element, 'getBoundingClientRect').mockReturnValue(rect(index * 40, 40))
  })
}
afterEach(() => { mounted.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })
describe('共享排序树', () => {
  it('键盘只在拿起把手后调整同级顺序，与节点选择分离', async () => {
    const wrapper = setup()
    await flushPromises()
    expect(wrapper.attributes('aria-label')).toBe('菜单树')
    const handle = wrapper.get(key('a'))
    await handle.trigger('keydown', { key: 'ArrowDown' })
    expect(wrapper.find('.is-dragging').exists()).toBe(false)
    await handle.trigger('keydown', { key: ' ' })
    await handle.trigger('keydown', { key: 'End' })
    expect(wrapper.find('[data-reorder-key="b"].is-drop-after').exists()).toBe(true)
    expect(wrapper.emitted('reorder')).toBeUndefined()
    await handle.trigger('keydown', { key: 'Enter' })
    const next = wrapper.emitted('reorder')![0][0] as Item[]
    expect(next[0].children.map(item => item.id)).toEqual(['b', 'a'])
    expect(next[1].children.map(item => item.id)).toEqual(['c'])
    expect(wrapper.emitted('select')).toBeUndefined()
    await wrapper.get('[role="treeitem"][data-key="b"]').trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('select')).toEqual([['b']])
  })
  it('拖动可移入另一分组，松手才提交；点把手不选择菜单', async () => {
    const wrapper = setup()
    await flushPromises()
    geometry(wrapper)
    wrapper.get(key('a')).element.dispatchEvent(pointer('pointerdown', 60))
    window.dispatchEvent(pointer('pointermove', 140))
    await nextTick()
    expect(wrapper.find('[data-reorder-key="g2"].is-drop-inside').exists()).toBe(true)
    expect(wrapper.text()).toContain('移入分组：g2')
    expect(wrapper.emitted('reorder')).toBeUndefined()
    window.dispatchEvent(pointer('pointerup', 140))
    const next = wrapper.emitted('reorder')![0][0] as Item[]
    expect(next[0].children.map(item => item.id)).toEqual(['b'])
    expect(next[1].children.map(item => item.id)).toEqual(['c', 'a'])
    await wrapper.get(key('a')).trigger('click')
    expect(wrapper.emitted('select')).toBeUndefined()
  })
  it('父节点不能拖入后代或叶子，Esc 取消预览', async () => {
    const wrapper = setup()
    await flushPromises()
    geometry(wrapper)
    wrapper.get(key('g1')).element.dispatchEvent(pointer('pointerdown', 20))
    window.dispatchEvent(pointer('pointermove', 60))
    window.dispatchEvent(pointer('pointerup', 60))
    expect(wrapper.emitted('reorder')).toBeUndefined()
    const handle = wrapper.get(key('a'))
    await handle.trigger('keydown', { key: ' ' })
    await handle.trigger('keydown', { key: 'End' })
    await handle.trigger('keydown', { key: 'Escape' })
    expect(wrapper.find('.is-dragging').exists()).toBe(false)
    expect(wrapper.emitted('reorder')).toBeUndefined()
  })
  it('移入折叠分组时展开目标，让已移动把手仍可见，保留原选中节点', async () => {
    const wrapper = setup({ currentKey: 'g1' })
    await flushPromises()
    await wrapper.get('[role="treeitem"][data-key="g2"] .el-tree-node__expand-icon').trigger('click')
    geometry(wrapper)
    wrapper.get(key('a')).element.dispatchEvent(pointer('pointerdown', 60))
    window.dispatchEvent(pointer('pointermove', 140))
    window.dispatchEvent(pointer('pointerup', 140))
    const next = wrapper.emitted('reorder')![0][0] as Item[]
    await wrapper.setProps({ items: next })
    await flushPromises()
    expect(wrapper.get('[role="treeitem"][data-key="g2"]').attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('[role="treeitem"][data-key="g1"]').classes()).toContain('is-current')
  })
  it('无排序权限不提供把手；忙态或编辑锁定拒绝排序', async () => {
    const wrapper = setup({ canReorder: false })
    expect(wrapper.find('.app-drag-handle').exists()).toBe(false)
    await wrapper.setProps({ canReorder: true, busy: true })
    expect(wrapper.findAll('.app-drag-handle').every(node => node.attributes('disabled') !== undefined)).toBe(true)
    await wrapper.get(key('a')).trigger('keydown', { key: ' ' })
    expect(wrapper.find('.is-dragging').exists()).toBe(false)
    await wrapper.setProps({ busy: false, disabled: true })
    await wrapper.get(key('a')).trigger('keydown', { key: ' ' })
    expect(wrapper.emitted('reorder')).toBeUndefined()
  })
  it('重载后保留选中和已折叠分组，保存结束恢复把手焦点', async () => {
    const wrapper = setup()
    await flushPromises()
    const group = wrapper.get('[role="treeitem"][data-key="g2"]')
    await group.get('.el-tree-node__expand-icon').trigger('click')
    expect(group.attributes('aria-expanded')).toBe('false')
    const handle = wrapper.get(key('a')).element as HTMLButtonElement
    handle.focus()
    await wrapper.setProps({ busy: true, items: data() })
    await wrapper.setProps({ busy: false })
    await flushPromises()
    expect(wrapper.get('[role="treeitem"][data-key="g2"]').attributes('aria-expanded')).toBe('false')
    expect(wrapper.get('[role="treeitem"][data-key="a"]').attributes('aria-current')).toBeUndefined()
    expect(wrapper.get('[role="treeitem"][data-key="a"]').classes()).toContain('is-current')
    expect(document.activeElement).toBe(wrapper.get(key('a')).element)
  })
})
