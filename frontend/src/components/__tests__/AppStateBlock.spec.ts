// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { defineComponent, h } from 'vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import appStateBlockSource from '@/components/AppStateBlock.vue?raw'

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

  it('empty 同时传标题和说明时完整展示两层信息', () => {
    const wrapper = mount(AppStateBlock, {
      props: { state: 'empty', title: '暂无生效规则', description: '该日期没有可补录规则' },
      global: { stubs },
    })

    expect(wrapper.get('.app-state-block__empty-copy').text()).toContain('暂无生效规则')
    expect(wrapper.get('.app-state-block__empty-copy').text()).toContain('该日期没有可补录规则')
  })

  it('empty 的说明与动作使用统一动作层分隔', () => {
    const wrapper = mount(AppStateBlock, {
      props: { state: 'empty', title: '暂无规则', description: '创建后即可开始使用' },
      slots: { extra: '<button>新建规则</button>' },
      global: { stubs },
    })

    expect(wrapper.get('.app-state-block__actions').text()).toContain('新建规则')
    expect(wrapper.get('.app-state-block__actions').element.previousElementSibling)
      .toBe(wrapper.get('.app-state-block__empty-copy').element)
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

  it('inline error 使用无插画短文案和文字重试动作', async () => {
    const wrapper = mount(AppStateBlock, {
      props: { state: 'error', size: 'inline', title: '方案加载失败', description: '网络异常', retry: true },
      global: { stubs },
    })

    expect(wrapper.find('.result-stub').exists()).toBe(false)
    expect(wrapper.get('.app-state-block__inline-error').text()).toContain('网络异常')
    await wrapper.get('.retry-btn').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })

  it('permission 作为 error 的语义变体使用无权限默认文案', () => {
    const wrapper = mount(AppStateBlock, {
      props: { state: 'error', variant: 'permission' },
      global: { stubs },
    })

    expect(wrapper.text()).toContain('无权限查看')
    expect(wrapper.text()).toContain('请联系系统管理员调整权限')
    expect(wrapper.find('.app-state-block__permission-icon').exists()).toBe(true)
    expect(wrapper.classes()).toContain('app-state-block--error')
    expect(wrapper.classes()).toContain('app-state-block--permission')
  })

  it('默认大尺寸空态与异常态占满可用区域并居中', () => {
    const defaultRule = appStateBlockSource.match(/\.app-state-block--default \{([^}]*)\}/)?.[1] || ''
    expect(defaultRule).toContain('align-items: center')
    expect(defaultRule).toContain('justify-content: center')
    expect(appStateBlockSource).toContain('.app-state-block--default.app-state-block--empty')
    expect(appStateBlockSource).toContain('.app-state-block--default.app-state-block--error')
    expect(appStateBlockSource).toContain('height: 100%')
    expect(appStateBlockSource).toContain('flex: 1 1 auto')
  })
})
