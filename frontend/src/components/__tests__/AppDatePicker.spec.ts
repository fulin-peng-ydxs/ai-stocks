// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppDatePicker from '@/components/AppDatePicker.vue'

function mountPicker(extraProps: Record<string, unknown> = {}, extraAttrs: Record<string, unknown> = {}) {
  return mount(AppDatePicker, {
    props: extraProps,
    attrs: { type: 'date', modelValue: '2026-09-01', ...extraAttrs },
    global: {
      stubs: {
        ElDatePicker: {
          name: 'ElDatePicker',
          props: ['modelValue', 'type', 'placement', 'fallbackPlacements'],
          template: '<input :value="modelValue" :data-type="type" />',
        },
      },
    },
  })
}

describe('AppDatePicker', () => {
  it.each([
    ['date', undefined],
    ['daterange', 'app-date-picker--range'],
    ['datetimerange', 'app-date-picker--datetime-range'],
  ])('%s 由共享适配器选择容量，保留日期值与调用方 fill', (type, variant) => {
    const wrapper = mountPicker({}, { type, class: 'app-control-width-fill' })
    expect(wrapper.classes()).toContain('app-date-picker')
    expect(wrapper.classes()).toContain('app-control-width-fill')
    if (variant) expect(wrapper.classes()).toContain(variant)
    else expect(wrapper.classes()).not.toContain('app-date-picker--datetime-range')
    expect(wrapper.findComponent({ name: 'ElDatePicker' }).props('modelValue')).toBe('2026-09-01')
    wrapper.unmount()
  })
  it('所有日期浮层默认只在触发器下方定位', () => {
    const picker = mountPicker().findComponent({ name: 'ElDatePicker' })

    expect(picker.props('placement')).toBe('bottom-start')
    expect(picker.props('fallbackPlacements')).toEqual(['bottom-start', 'bottom-end'])
    expect(picker.props('modelValue')).toBe('2026-09-01')
    expect(picker.props('type')).toBe('date')
  })

  it('明确的特殊场景仍可覆盖浮层位置', () => {
    const picker = mountPicker({
      placement: 'top-start',
      fallbackPlacements: ['top-start'],
    }).findComponent({ name: 'ElDatePicker' })

    expect(picker.props('placement')).toBe('top-start')
    expect(picker.props('fallbackPlacements')).toEqual(['top-start'])
  })
})
