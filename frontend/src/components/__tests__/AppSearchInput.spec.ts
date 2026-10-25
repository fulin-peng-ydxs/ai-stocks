// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import AppForm from '@/components/AppForm.vue'
import ElementPlus from 'element-plus'
import AppSearchInput from '@/components/AppSearchInput.vue'

function mountSearch(props: Record<string, unknown> = {}) {
  return mount(AppSearchInput, {
    props: { modelValue: '', ...props },
    global: { plugins: [ElementPlus] },
  })
}

describe('AppSearchInput', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('未指定尺寸时动态继承所属表单，保留输入与查询行为', async () => {
    const wrapper = mount(defineComponent({
      components: { AppForm, AppSearchInput },
      props: { size: { type: String, default: 'large' } },
      template: '<AppForm :size="size"><AppSearchInput model-value="保留搜索" /></AppForm>',
    }), { global: { plugins: [ElementPlus] } })
    try {
      const input = wrapper.get('input').element
      expect(wrapper.find('.el-input--large').exists()).toBe(true)
      await wrapper.setProps({ size: 'small' })
      expect(wrapper.find('.el-input--small').exists()).toBe(true)
      expect(wrapper.get('input').element).toBe(input)
      expect((input as HTMLInputElement).value).toBe('保留搜索')
      await wrapper.get('input').trigger('keydown', { key: 'Enter' })
      expect(wrapper.findComponent(AppSearchInput).emitted('search')).toHaveLength(1)
    } finally {
      wrapper.unmount()
    }
  })

  it('输入即同步值，并防抖后只发一次 search', async () => {
    const wrapper = mountSearch({ placeholder: '代码 / 名称' })
    const input = wrapper.find('input')
    await input.setValue('abc')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['abc'])
    expect(wrapper.emitted('search')).toBeUndefined()

    await input.setValue('abcd')
    await input.setValue('abcde')
    vi.advanceTimersByTime(300)
    expect(wrapper.emitted('search')).toHaveLength(1)
  })

  it('回车立即发 search', async () => {
    const wrapper = mountSearch()
    const input = wrapper.find('input')
    await input.setValue('abc')
    await input.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('search')).toHaveLength(1)
    // flush 已取消防抖队列，因此不会再触发
    vi.advanceTimersByTime(300)
    expect(wrapper.emitted('search')).toHaveLength(1)
  })

  it('防抖查询已经完成后，同值回车不重复查询', async () => {
    const wrapper = mountSearch()
    const input = wrapper.find('input')
    await input.setValue('abc')
    vi.advanceTimersByTime(300)
    expect(wrapper.emitted('search')).toHaveLength(1)

    await input.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('search')).toHaveLength(1)

    vi.advanceTimersByTime(301)
    await input.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('search')).toHaveLength(2)
  })

  it('清空立即发 search 且值清空', async () => {
    const wrapper = mountSearch({ modelValue: 'abc' })
    const input = wrapper.find('input')
    await input.setValue('abc')
    const clear = wrapper.find('.el-input__clear')
    await clear.trigger('click')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([''])
    expect(wrapper.emitted('search')).toHaveLength(1)
  })
})
