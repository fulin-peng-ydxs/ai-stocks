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
      directives: { permission: {} },
      stubs: {
        HelpHint: {
          props: ['text'],
          template: '<span class="help-hint-stub">{{ text }}</span>',
        },
        ElForm: { template: '<form><slot /></form>' },
        ElFormItem: {
          template: '<div class="form-item"><slot name="label" /><slot /></div>',
        },
        ElSwitch: { name: 'ElSwitch', props: ['modelValue'], template: '<button>{{ String(modelValue) }}</button>' },
        ElSelect: { template: '<div><slot /></div>' },
        ElOption: true,
        ElInputNumber: { name: 'ElInputNumber', emits: ['update:modelValue'], props: ['modelValue'], template: '<input :value="modelValue" />' },
        ElButton: { template: '<button><slot /></button>' },
        ElInput: {
          props: ['modelValue', 'type'],
          emits: ['update:modelValue'],
          template: '<input :value="modelValue" :type="type" @input="$emit(\'update:modelValue\', $event.target.value)" />',
        },
        ElIcon: { template: '<i><slot /></i>' },
      },
    },
  })
}

describe('ConfigGroupForm', () => {
  it('来源覆盖以显式继承开关表达，关闭后提交 null', async () => {
    const field = { path: 'ths_board.timeout_sec', label: '旧请求超时', type: 'number',
      value: null, default: null, overridden: false, nullable: true, min: 1, inherited_value: 30 }
    const wrapper = mountForm({ group: { key: 'ths_board', label: '板块', fields: [field] },
      modelValue: { 'ths_board.timeout_sec': null } })
    expect(wrapper.findComponent({ name: 'ElInputNumber' }).exists()).toBe(false)
    expect(wrapper.text()).toContain('当前继承：30')
    const toggle = wrapper.findComponent({ name: 'ElSwitch' })
    toggle.vm.$emit('update:modelValue', true)
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('update-field')?.[0]).toEqual(['ths_board.timeout_sec', 30])
    toggle.vm.$emit('update:modelValue', false)
    expect(wrapper.emitted('update-field')?.[1]).toEqual(['ths_board.timeout_sec', null])
  })

  it('密文不可用时仍提供清除入口，不要求先解密出原值', async () => {
    const wrapper = mountForm({ group: { key: 'ths_board', label: '板块', fields: [{
      path: 'ths_board.login_cookie', label: 'Cookie', type: 'password', value: '',
      default: '', overridden: true, secret_status: 'unavailable',
    }] }, modelValue: { 'ths_board.login_cookie': '' } })
    await wrapper.findAll('button').find((button) => button.text() === '清除已存配置')!.trigger('click')
    expect(wrapper.emitted('reset-field')?.[0]).toEqual(['ths_board.login_cookie'])
  })

  it('把字段描述、默认值和范围传给 HelpHint', () => {
    const wrapper = mountForm()
    const helpTexts = wrapper.findAll('.help-hint-stub').map((node) => node.text())
    expect(helpTexts.some((text) => text.includes('失败达到阈值后要求图形验证码。'))).toBe(true)
    expect(helpTexts.some((text) => text.includes('默认值：3'))).toBe(true)
    expect(helpTexts.some((text) => text.includes('允许范围：1 - 10'))).toBe(true)
  })

  it('数值和枚举配置显示必填标记语义，开关不误标', () => {
    const wrapper = mountForm()
    const items = wrapper.findAll('.form-item')
    expect(items[0].attributes('required')).toBeDefined()
    expect(items[1].attributes('required')).toBe('false')
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

  it('password 型字段渲染密码输入框、初始只读防自动填充，聚焦后可编辑并透传值', async () => {
    const groupWithPwd: SettingGroup = {
      ...group,
      fields: [
        ...group.fields,
        {
          path: 'example.password',
          label: '示例密码',
          desc: '验证通用 password 字段渲染。',
          type: 'password',
          value: '••••••已设置',
          default: '',
          overridden: true,
          placeholder: '已设置，留空不修改',
        },
      ],
    }
    const wrapper = mount(ConfigGroupForm as Component, {
      props: {
        group: groupWithPwd,
        modelValue: { 'example.password': '••••••已设置' },
      },
      global: {
        stubs: {
          HelpHint: { template: '<span />' },
          ElForm: { template: '<form><slot /></form>' },
          ElFormItem: { template: '<div><slot name="label" /><slot /></div>' },
          ElSwitch: { template: '<button />' },
          ElSelect: { template: '<div><slot /></div>' },
          ElOption: true,
          ElInputNumber: { template: '<input />' },
          ElButton: { template: '<button><slot /></button>' },
        ElInput: {
            props: ['modelValue', 'type'],
            emits: ['update:modelValue'],
            template: '<input :value="modelValue" :type="type" @input="$emit(\'update:modelValue\', $event.target.value)" />',
          },
          ElIcon: { template: '<i><slot /></i>' },
        },
      },
    })
    const pwdInput = wrapper.find('input[type="password"]')
    expect(pwdInput.exists()).toBe(true)
    expect(pwdInput.attributes('value')).toBe('••••••已设置')
    // 防浏览器自动填充（如把登录密码 Admin@12345 误填进同花顺 Cookie 输入框）：
    // 初始 readonly + autocomplete=new-password，聚焦后才移除 readonly 允许输入。
    expect(pwdInput.element.hasAttribute('readonly')).toBe(true)
    expect(pwdInput.attributes('autocomplete')).toBe('new-password')
    await pwdInput.trigger('focus')
    expect(pwdInput.element.hasAttribute('readonly')).toBe(false)
    // 触发输入 → 发 update-field 事件携带新值
    await pwdInput.setValue('new-secret')
    const emitted = wrapper.emitted('update-field')
    expect(emitted).toBeTruthy()
    expect(emitted![0]).toEqual(['example.password', 'new-secret'])
  })
})
