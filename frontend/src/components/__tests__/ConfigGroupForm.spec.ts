// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import type { Component } from 'vue'
import ConfigGroupForm from '@/components/config/ConfigGroupForm.vue'
import type { SettingGroup } from '@/api/data'

const group: SettingGroup = {
  key: 'auth',
  label: '认证与防滥用',
  desc: '控制认证和防滥用策略。',
  fields: [
    {
      path: 'auth.captcha_after_fails',
      label: '图形验证码强制失败次数',
      desc: '失败达到阈值后要求图形验证码。',
      type: 'int',
      value: 3,
      default: 3,
      overridden: false,
      min: 1,
      max: 10,
    },
    {
      path: 'auth.require_email_code',
      label: '注册需邮箱验证码',
      desc: '开启后自助注册必须提交真实邮箱验证码。',
      type: 'bool',
      value: true,
      default: true,
      overridden: false,
    },
  ],
}

function mountForm(extraProps: Record<string, unknown> = {}) {
  return mount(ConfigGroupForm as Component, {
    props: {
      group,
      modelValue: {
        'auth.captcha_after_fails': 3,
        'auth.require_email_code': true,
      },
      ...extraProps,
    },
    global: {
      stubs: {
        HelpHint: {
          props: ['text'],
          template: '<span class="help-hint-stub">{{ text }}</span>',
        },
        ElForm: { template: '<form><slot /></form>' },
        ElFormItem: {
          template: '<div class="form-item"><slot name="label" /><slot /></div>',
        },
        ElSwitch: { props: ['modelValue'], template: '<button>{{ String(modelValue) }}</button>' },
        ElSelect: { template: '<div><slot /></div>' },
        ElOption: true,
        ElInputNumber: { props: ['modelValue'], template: '<input :value="modelValue" />' },
        ElIcon: { template: '<i><slot /></i>' },
      },
    },
  })
}

describe('ConfigGroupForm', () => {
  it('把字段描述、默认值和范围传给 HelpHint', () => {
    const wrapper = mountForm()
    const helpTexts = wrapper.findAll('.help-hint-stub').map((node) => node.text())
    expect(helpTexts.some((text) => text.includes('失败达到阈值后要求图形验证码。'))).toBe(true)
    expect(helpTexts.some((text) => text.includes('默认值：3'))).toBe(true)
    expect(helpTexts.some((text) => text.includes('允许范围：1 - 10'))).toBe(true)
  })

  it('按 config-panel 行为控制折叠态和说明展示', () => {
    const wrapper = mountForm({
      sections: [
        {
          key: 'login',
          title: '登录保护',
          hint: '登录区说明。',
          fieldPaths: ['auth.captcha_after_fails'],
        },
      ],
      panelBehavior: {
        collapsibleSections: true,
        defaultCollapsed: ['auth', 'auth.login'],
        showGroupDescription: false,
        showSectionDescription: false,
      },
    })

    const groupSection = wrapper.find('.config-panel-section.is-level-1')
    const blockSection = wrapper.findAll('.config-panel-section.is-level-2')
      .find((node) => node.text().includes('登录保护'))
    expect(groupSection.classes()).toContain('is-closed')
    expect(blockSection?.classes()).toContain('is-closed')
    expect(wrapper.text()).not.toContain('控制认证和防滥用策略。')
    expect(wrapper.text()).not.toContain('登录区说明。')
  })

  it('未归入已知分区的字段进入其他配置兜底分块', () => {
    const wrapper = mountForm({
      sections: [
        {
          key: 'login',
          title: '登录保护',
          fieldPaths: ['auth.captcha_after_fails'],
        },
      ],
    })

    expect(wrapper.text()).toContain('登录保护')
    expect(wrapper.text()).toContain('其他配置')
    expect(wrapper.text()).toContain('注册需邮箱验证码')
  })

  it('禁用折叠时忽略默认折叠值并保持展开态', () => {
    const wrapper = mountForm({
      sections: [
        {
          key: 'login',
          title: '登录保护',
          fieldPaths: ['auth.captcha_after_fails'],
        },
      ],
      panelBehavior: {
        collapsibleSections: false,
        defaultCollapsed: ['auth', 'auth.login'],
        showGroupDescription: true,
        showSectionDescription: true,
      },
    })

    expect(wrapper.find('.config-panel-section.is-level-1').classes()).not.toContain('is-closed')
    const blockSection = wrapper.findAll('.config-panel-section.is-level-2')
      .find((node) => node.text().includes('登录保护'))
    expect(blockSection?.classes()).not.toContain('is-closed')
    expect(wrapper.text()).toContain('图形验证码强制失败次数')
  })
})
