// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { defineComponent, h } from 'vue'
import AppStateBlock from '@/components/AppStateBlock.vue'

const ElSkeletonStub = defineComponent({
  name: 'ElSkeleton',
  props: ['rows'],
  setup(props) {
    return () => h('div', { class: 'skeleton-stub' }, `rows:${props.rows}`)
  },
})

const ElEmptyStub = defineComponent({
  name: 'ElEmpty',
  props: ['description'],
  setup(props, { slots }) {
    return () => h('div', { class: 'empty-stub' }, [
      h('span', { class: 'empty-desc' }, String(props.description || '')),
      slots.default?.(),
    ])
  },
})

const ElResultStub = defineComponent({
  name: 'ElResult',
  props: ['title'],
  setup(props, { slots }) {
    return () => h('div', { class: 'result-stub' }, [
      h('div', { class: 'icon' }, slots.icon?.()),
      h('h3', String(props.title || '')),
      h('p', { class: 'subtitle' }, slots['sub-title']?.()),
      h('div', { class: 'extra' }, slots.extra?.()),
    ])
  },
})

const ElButtonStub = defineComponent({
  name: 'ElButton',
  emits: ['click'],
  setup(_props, { slots, emit }) {
    return () => h('button', { class: 'retry-btn', onClick: () => emit('click') }, slots.default?.())
  },
})

const ElIconStub = defineComponent({
  name: 'ElIcon',
  setup(_props, { slots }) {
    return () => h('span', { class: 'el-icon-stub' }, slots.default?.())
  },
})

const stubs = {
  ElSkeleton: ElSkeletonStub,
  ElEmpty: ElEmptyStub,
  ElResult: ElResultStub,
  ElButton: ElButtonStub,
  ElIcon: ElIconStub,
}

describe('AppStateBlock', () => {
  it('loading 使用骨架屏并显示说明', () => {
    const wrapper = mount(AppStateBlock, {
      props: { state: 'loading', title: '正在加载数据...', skeletonRows: 4 },
      global: { stubs },
    })

    expect(wrapper.text()).toContain('rows:4')
    expect(wrapper.text()).toContain('正在加载数据...')
  })

  it('empty 使用统一空态文案', () => {
    const wrapper = mount(AppStateBlock, {
      props: { state: 'empty', description: '暂无记录', size: 'compact' },
      global: { stubs },
    })

    expect(wrapper.find('.empty-stub').exists()).toBe(true)
    expect(wrapper.text()).toContain('暂无记录')
    expect(wrapper.find('.app-state-block--compact').exists()).toBe(true)
  })

  it('inline empty 使用紧凑内联空态', () => {
    const wrapper = mount(AppStateBlock, {
      props: { state: 'empty', size: 'inline', description: '无匹配结果' },
      global: { stubs },
    })

    expect(wrapper.find('.app-empty-inline').exists()).toBe(true)
    expect(wrapper.text()).toContain('无匹配结果')
  })

  it('error 显示重试按钮并派发 retry', async () => {
    const wrapper = mount(AppStateBlock, {
      props: { state: 'error', title: '列表加载失败', retry: true },
      global: { stubs },
    })

    expect(wrapper.text()).toContain('列表加载失败')
    expect(wrapper.text()).toContain('请检查网络或稍后重试')
    await wrapper.find('.retry-btn').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })

  it('permission 使用无权限默认文案', () => {
    const wrapper = mount(AppStateBlock, {
      props: { state: 'permission' },
      global: { stubs },
    })

    expect(wrapper.text()).toContain('无权限查看')
    expect(wrapper.text()).toContain('请联系系统管理员调整权限')
    expect(wrapper.find('.app-state-block__permission-icon').exists()).toBe(true)
  })
})
