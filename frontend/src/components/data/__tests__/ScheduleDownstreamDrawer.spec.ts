// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import ScheduleDownstreamDrawer from '../ScheduleDownstreamDrawer.vue'
import type { ScheduledJob } from '@/api/data'

const api = vi.hoisted(() => ({ list: vi.fn(), save: vi.fn() }))
vi.mock('@/api/data', async importOriginal => ({
  ...await importOriginal<object>(),
  listScheduleDownstream: (...args: unknown[]) => api.list(...args),
  saveScheduleDownstreamOrder: (...args: unknown[]) => api.save(...args),
}))
const item = (id: string, enabled = true) => ({
  id, name: `任务${id}`, task_type: 'verify', params: {}, enabled,
  dependency_condition: 'success', dependency_delay: { value: 5, unit: 'minute' },
} as ScheduledJob)
const a = item('a'), b = item('b', false), parent = item('root')
const result = () => ({ jobs: [a, b], revision: 'v1' })
const wrappers: ReturnType<typeof mount>[] = []
async function setup() {
  const wrapper = mount(ScheduleDownstreamDrawer, {
    props: { modelValue: true, job: parent },
    global: { plugins: [ElementPlus], directives: { permission: {} }, stubs: {
      AppDetailDrawer: {
        name: 'AppDetailDrawer',
        props: ['modelValue', 'state', 'stateTitle', 'stateDescription', 'beforeClose'],
        template: '<div><span>{{ stateTitle }} {{ stateDescription }}</span><slot v-if="state === \'ready\'"/><slot name="footer"/></div>',
      },
    } }, attachTo: document.body,
  })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
function button(wrapper: ReturnType<typeof mount>, label: string) {
  return wrapper.findAll('button').find(node => node.text() === label)!
}
beforeEach(() => {
  vi.clearAllMocks()
  api.list.mockResolvedValue(result())
  api.save.mockResolvedValue({ jobs: [b, a], revision: 'v2' })
})
afterEach(() => {
  wrappers.splice(0).forEach(wrapper => wrapper.unmount())
  vi.restoreAllMocks()
})
describe('下游任务查看和顺序保存', () => {
  it('展示停用任务和触发条件，无变化不能保存；键盘只改草稿', async () => {
    const wrapper = await setup()
    expect(wrapper.text()).toContain('已停用 · 不自动触发')
    expect(wrapper.text()).toContain('成功后 · 延迟 5 分钟')
    expect(button(wrapper, '保存顺序').attributes('disabled')).toBeDefined()
    const list = wrapper.getComponent({ name: 'AppReorderList' })
    await list.get('[aria-label="拖动排序：任务a"]').trigger('keydown', { key: ' ' })
    await list.get('[aria-label="拖动排序：任务a"]').trigger('keydown', { key: 'End' })
    await list.get('[aria-label="拖动排序：任务a"]').trigger('keydown', { key: 'Enter' })
    expect(list.props('items').map((job: ScheduledJob) => job.id)).toEqual(['b', 'a'])
    expect(api.save).not.toHaveBeenCalled()
    await button(wrapper, '保存顺序').trigger('click')
    await flushPromises()
    expect(api.save).toHaveBeenCalledWith('root', ['b', 'a'], 'v1')
    expect(button(wrapper, '保存顺序').attributes('disabled')).toBeDefined()
  })
  it('保存中拒绝重入，失败保留草稿与版本并支持重试', async () => {
    let reject!: (error: Error) => void
    api.save.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail }))
    const wrapper = await setup()
    wrapper.getComponent({ name: 'AppReorderList' }).vm.$emit('reorder', [b, a])
    await flushPromises()
    await button(wrapper, '保存顺序').trigger('click')
    await button(wrapper, '保存顺序').trigger('click')
    expect(api.save).toHaveBeenCalledOnce()
    expect(wrapper.getComponent({ name: 'AppReorderList' }).props('disabled')).toBe(true)
    reject(new Error('下游关系或顺序已变化，请刷新后重新调整'))
    await flushPromises()
    expect(wrapper.text()).toContain('下游关系或顺序已变化')
    expect(wrapper.getComponent({ name: 'AppReorderList' }).props('items').map((job: ScheduledJob) => job.id)).toEqual(['b', 'a'])
    await button(wrapper, '保存顺序').trigger('click')
    await flushPromises()
    expect(api.save).toHaveBeenLastCalledWith('root', ['b', 'a'], 'v1')
  })
  it('关闭和刷新均确认未保存草稿，取消时保留修改', async () => {
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue('cancel')
    const wrapper = await setup()
    wrapper.getComponent({ name: 'AppReorderList' }).vm.$emit('reorder', [b, a])
    await flushPromises()
    await button(wrapper, '关闭').trigger('click')
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    await button(wrapper, '刷新').trigger('click')
    await flushPromises()
    expect(api.list).toHaveBeenCalledOnce()
    confirm.mockImplementation(() => Promise.resolve('confirm') as ReturnType<typeof ElMessageBox.confirm>)
    await button(wrapper, '关闭').trigger('click')
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
  })
  it('切换任务忽略旧请求，关闭时清空草稿', async () => {
    let finish!: (value: ReturnType<typeof result>) => void
    api.list.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = await setup()
    await wrapper.setProps({ job: item('other') })
    await flushPromises()
    finish({ jobs: [item('stale')], revision: 'old' })
    await flushPromises()
    expect(wrapper.getComponent({ name: 'AppReorderList' }).props('items').map((job: ScheduledJob) => job.id)).toEqual(['a', 'b'])
    await wrapper.setProps({ modelValue: false })
    expect(wrapper.findComponent({ name: 'AppReorderList' }).exists()).toBe(false)
  })
  it('加载错误、空态和重试通过共享抽屉承接', async () => {
    api.list.mockRejectedValueOnce(new Error('加载出错'))
    const wrapper = await setup()
    const drawer = wrapper.getComponent({ name: 'AppDetailDrawer' })
    expect(drawer.props('state')).toBe('error')
    expect(wrapper.text()).toContain('加载出错')
    api.list.mockResolvedValue({ jobs: [], revision: 'empty' })
    drawer.vm.$emit('retry')
    await flushPromises()
    expect(drawer.props('state')).toBe('empty')
    expect(button(wrapper, '保存顺序').attributes('disabled')).toBeDefined()
  })
})
