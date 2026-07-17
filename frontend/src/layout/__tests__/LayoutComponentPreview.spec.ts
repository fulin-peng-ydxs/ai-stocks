// @vitest-environment jsdom
import { shallowMount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { defineComponent, h } from 'vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import LayoutComponentPreview from '@/layout/components/LayoutComponentPreview.vue'
import { COMPONENT_CATALOG } from '@/layout/components'
import type { ComponentKind } from '@/layout/schema'

describe('LayoutComponentPreview 四态规范样板', () => {
  const global = {
    stubs: {
      ElIcon: defineComponent({
        name: 'ElIcon',
        setup(_props, { slots }) {
          return () => h('span', slots.default?.())
        },
      }),
    },
  }

  it('ready 渲染组件原型，不渲染状态组件', () => {
    const wrapper = shallowMount(LayoutComponentPreview, {
      props: { kind: 'data-table', state: 'ready' },
      global,
    })

    expect(wrapper.find('.cp-table').exists()).toBe(true)
    expect(wrapper.findComponent(AppStateBlock).exists()).toBe(false)
  })

  it('目录中的每个组件都通过 AppStateBlock 统一渲染非 ready 三态', () => {
    for (const kind of Object.keys(COMPONENT_CATALOG) as ComponentKind[]) {
      for (const state of ['loading', 'empty', 'error'] as const) {
        const wrapper = shallowMount(LayoutComponentPreview, {
          props: { kind, state },
          global,
        })

        const block = wrapper.findComponent(AppStateBlock)
        expect(block.exists(), `${kind} 缺少 ${state} 统一状态组件`).toBe(true)
        expect(block.props('state')).toBe(state)
        expect(block.props('size')).toBe('compact')
      }
    }
  })

  it('反馈类组件在 ready 请求下仍使用其约定状态', () => {
    const wrapper = shallowMount(LayoutComponentPreview, {
      props: { kind: 'empty-state', state: 'ready' },
      global,
    })

    expect(wrapper.findComponent(AppStateBlock).props('state')).toBe('empty')
  })
})
