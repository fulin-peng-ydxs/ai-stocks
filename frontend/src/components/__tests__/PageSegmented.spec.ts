// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PageSegmented from '../PageSegmented.vue'

describe('PageSegmented', () => {
  it('supports a compact size for page control rows', () => {
    const wrapper = mount(PageSegmented, {
      props: {
        modelValue: 'all',
        size: 'small',
        options: [{ label: '全部', value: 'all' }],
      },
    })

    expect(wrapper.classes()).toContain('page-segmented--small')
  })

  it('supports the shared primary tone for page-level mode switches', () => {
    const wrapper = mount(PageSegmented, {
      props: {
        modelValue: 'all',
        tone: 'primary',
        options: [{ label: '全部', value: 'all' }],
      },
    })

    expect(wrapper.classes()).toContain('page-segmented--primary')
  })

  it('按需输出稳定 E2E 锚点，不影响原有分段选择行为', async () => {
    const wrapper = mount(PageSegmented, {
      props: {
        modelValue: 'md',
        'aria-label': '抽屉尺寸',
        testId: 'drawer-size',
        options: [
          { label: '小', value: 'sm' },
          { label: '中', value: 'md' },
          { label: '大', value: 'lg' },
        ],
      },
    })

    expect(wrapper.attributes('role')).toBe('group')
    expect(wrapper.attributes('aria-label')).toBe('抽屉尺寸')
    expect(wrapper.attributes('data-testid')).toBe('drawer-size')
    expect(wrapper.get('[data-testid="drawer-size-md"]').classes()).toContain('active')
    expect(wrapper.get('[data-testid="drawer-size-md"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[data-testid="drawer-size-sm"]').attributes('aria-pressed')).toBe('false')

    await wrapper.get('[data-testid="drawer-size-lg"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['lg'])

    await wrapper.setProps({ modelValue: 'lg' })
    expect(wrapper.get('[data-testid="drawer-size-md"]').attributes('aria-pressed')).toBe('false')
    expect(wrapper.get('[data-testid="drawer-size-lg"]').attributes('aria-pressed')).toBe('true')
  })

  it('支持由页面已有标题提供可访问名称关联', () => {
    const wrapper = mount(PageSegmented, {
      props: {
        modelValue: 'all',
        'aria-label': '显示范围',
        'aria-labelledby': 'source-mode-label',
        options: [
          { label: '全部源', value: 'all' },
          { label: '只主源', value: 'primary' },
        ],
      },
    })

    expect(wrapper.attributes('role')).toBe('group')
    expect(wrapper.attributes('aria-label')).toBe('显示范围')
    expect(wrapper.attributes('aria-labelledby')).toBe('source-mode-label')
  })

  it('可选 icon slot 注入前置图标并接收 option/active 上下文，缺省保持纯文字', () => {
    const withIcon = mount(PageSegmented, {
      props: {
        modelValue: 'dark',
        options: [
          { label: '白天', value: 'light' },
          { label: '夜间', value: 'dark' },
        ],
      },
      slots: {
        icon: `<template #icon="{ option, active }"><i :class="'orb-' + option.value + (active ? ' on' : '')" /></template>`,
      },
    })
    expect(withIcon.find('.orb-light').exists()).toBe(true)
    expect(withIcon.find('.orb-dark').classes()).toContain('on')
    expect(withIcon.find('.orb-light').classes()).not.toContain('on')

    const plain = mount(PageSegmented, {
      props: { modelValue: 'a', options: [{ label: '甲', value: 'a' }] },
    })
    expect(plain.find('.seg-btn i').exists()).toBe(false)
    expect(plain.get('.seg-btn').text()).toBe('甲')
  })
})
