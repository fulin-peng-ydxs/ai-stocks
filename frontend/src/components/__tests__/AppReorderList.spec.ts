// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { h, nextTick, toRaw } from 'vue'
import AppReorderList from '@/components/AppReorderList.vue'

const items = [{ id: 'a', name: '甲' }, { id: 'b', name: '乙' }, { id: 'c', name: '丙' }]
const mounted: ReturnType<typeof mount>[] = []
function setup() {
  const wrapper = mount(AppReorderList<(typeof items)[number]>, {
    props: { items, itemKey: item => item.id, itemLabel: item => item.name, label: '规则排序' },
    slots: { default: ({ item }: any) => h('input', { value: item.name }) },
    attachTo: document.body,
  })
  mounted.push(wrapper)
  const rect = (top: number, height: number) => ({ top, bottom: top + height, left: 0, right: 400, width: 400, height, x: 0, y: top, toJSON() {} })
  vi.spyOn(wrapper.element, 'getBoundingClientRect').mockReturnValue(rect(0, 180))
  wrapper.findAll('[data-reorder-key]').forEach((row, index) => {
    vi.spyOn(row.element, 'getBoundingClientRect').mockReturnValue(rect(index * 60, 60))
  })
  return wrapper
}
function pointer(type: string, x = 20, y = 170, id = 1) {
  const event = new Event(type, { bubbles: true, cancelable: true })
  Object.defineProperties(event, {
    pointerId: { value: id }, clientX: { value: x }, clientY: { value: y }, button: { value: 0 },
  })
  return event
}
async function start(wrapper: ReturnType<typeof setup>) {
  wrapper.get('[aria-label="拖动排序：甲"]').element.dispatchEvent(pointer('pointerdown', 20, 20))
  await nextTick()
}

describe('AppReorderList', () => {
  afterEach(() => {
    mounted.splice(0).forEach(wrapper => wrapper.unmount())
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('拖动仅预览落点，松手提交远距离移动并保留原对象与输入节点', async () => {
    const wrapper = setup()
    const input = wrapper.findAll('input')[0].element
    await start(wrapper)
    window.dispatchEvent(pointer('pointermove'))
    await nextTick()
    expect(wrapper.findAll('.is-drop-after')).toHaveLength(1)
    expect(wrapper.emitted('reorder')).toBeUndefined()
    window.dispatchEvent(pointer('pointerup'))
    await nextTick()
    const result = wrapper.emitted('reorder')![0][0] as typeof items
    expect(result.map(item => item.id)).toEqual(['b', 'c', 'a'])
    expect(toRaw(result[2])).toBe(items[0])
    expect(items.map(item => item.id)).toEqual(['a', 'b', 'c'])
    expect(document.activeElement?.getAttribute('aria-label')).toBe('拖动排序：甲')
    await wrapper.setProps({ items: result })
    expect(wrapper.findAll('input')[2].element).toBe(input)
  })

  it.each(['outside', 'pointercancel', 'Escape', 'blur', 'visibility', 'data', 'replacement', 'disabled', 'unmount'])(
    '%s 取消拖动且不提交旧列表', async reason => {
      const wrapper = setup()
      await start(wrapper)
      window.dispatchEvent(pointer('pointermove'))
      if (reason === 'outside') window.dispatchEvent(pointer('pointermove', 500))
      if (reason === 'pointercancel') window.dispatchEvent(pointer('pointercancel'))
      if (reason === 'Escape') window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
      if (reason === 'blur') window.dispatchEvent(new Event('blur'))
      if (reason === 'visibility') document.dispatchEvent(new Event('visibilitychange'))
      if (reason === 'replacement') await wrapper.setProps({ items: items.map(item => ({ ...item })) })
      if (reason === 'data') await wrapper.setProps({ items: [items[1], items[0], items[2]] })
      if (reason === 'disabled') await wrapper.setProps({ disabled: true })
      if (reason === 'unmount') wrapper.unmount()
      window.dispatchEvent(pointer('pointerup', reason === 'outside' ? 500 : 20))
      expect(wrapper.emitted('reorder')).toBeUndefined()
    },
  )

  it('轻点和其他指针不重排，编辑输入不触发拖动', async () => {
    const wrapper = setup()
    await wrapper.get('input').trigger('pointerdown', { pointerId: 1, button: 0 })
    window.dispatchEvent(pointer('pointerup'))
    await start(wrapper)
    window.dispatchEvent(pointer('pointermove', 20, 170, 2))
    window.dispatchEvent(pointer('pointerup', 20, 20))
    expect(wrapper.emitted('reorder')).toBeUndefined()
  })

  it('键盘预览可取消，确认后从首项移到末项，不显示点击移动按钮', async () => {
    const wrapper = setup()
    const handle = wrapper.get('[aria-label="拖动排序：甲"]')
    await handle.trigger('keydown', { key: ' ' })
    await handle.trigger('keydown', { key: 'End' })
    expect(wrapper.emitted('reorder')).toBeUndefined()
    await handle.trigger('keydown', { key: 'Escape' })
    await handle.trigger('keydown', { key: ' ' })
    await handle.trigger('keydown', { key: 'End' })
    await handle.trigger('keydown', { key: 'Home' })
    await handle.trigger('keydown', { key: 'ArrowUp' })
    await handle.trigger('keydown', { key: 'ArrowDown' })
    await handle.trigger('keydown', { key: 'Enter' })
    expect((wrapper.emitted('reorder')![0][0] as typeof items).map(item => item.id)).toEqual(['b', 'a', 'c'])
    expect(wrapper.find('[aria-label*="上移"]').exists()).toBe(false)
  })

  it('键盘排序离开把手后取消，不残留待提交顺序', async () => {
    const wrapper = setup()
    const handle = wrapper.get('[aria-label="拖动排序：甲"]')
    await handle.trigger('keydown', { key: ' ' })
    await handle.trigger('keydown', { key: 'End' })
    await handle.trigger('blur')
    expect(wrapper.find('.is-dragging').exists()).toBe(false)
    expect(wrapper.emitted('reorder')).toBeUndefined()
  })

  it('只读及单项列表无把手', async () => {
    const wrapper = setup()
    await wrapper.setProps({ disabled: true })
    expect(wrapper.find('button').exists()).toBe(false)
    await wrapper.setProps({ disabled: false, items: [items[0]] })
    expect(wrapper.find('button').exists()).toBe(false)
  })

  it('长列表拖动到容器边缘自动滚动，取消释放动画帧', async () => {
    let callback: FrameRequestCallback | undefined
    vi.stubGlobal('requestAnimationFrame', vi.fn(fn => { callback = fn; return 1 }))
    const cancelFrame = vi.fn()
    vi.stubGlobal('cancelAnimationFrame', cancelFrame)
    const wrapper = setup()
    const parent = wrapper.element.parentElement!
    parent.style.overflowY = 'auto'
    vi.spyOn(parent, 'getBoundingClientRect').mockReturnValue({ top: 0, bottom: 180, left: 0, right: 400 } as DOMRect)
    await start(wrapper)
    window.dispatchEvent(pointer('pointermove'))
    callback?.(0)
    expect(parent.scrollTop).toBe(10)
    window.dispatchEvent(pointer('pointercancel'))
    expect(cancelFrame).toHaveBeenCalledWith(1)
  })
})
