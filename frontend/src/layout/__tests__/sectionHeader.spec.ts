// @vitest-environment jsdom
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import ConfigPanelSection from '@/components/config/ConfigPanelSection.vue'
import SettingsGroup from '@/components/SettingsGroup.vue'
import PermissionTree from '@/views/system/PermissionTree.vue'
import { auditSharedStyles } from '../../../scripts/check-design-contracts.mjs'
import { designContracts } from '../../../scripts/design-source.mjs'

describe('分组标题共享角色', () => {
  it('一级配置与权限标题共用浅底，轻量配置和设置标题显式选择透明形态', async () => {
    const config = mount(ConfigPanelSection, { props: { title: '数据源' } })
    const settings = mount(SettingsGroup, { props: { title: '外观' } })
    expect(config.get('.config-panel-section__head').classes()).toContain('app-section-header')
    expect(config.get('.config-panel-section__head').classes()).not.toContain('app-section-header--plain')
    await config.setProps({ level: 2 })
    expect(config.get('.config-panel-section__head').classes()).toContain('app-section-header--plain')
    expect(settings.get('.sg-head').classes()).toContain('app-section-header--plain')
    config.unmount()
    settings.unmount()
  })

  it('配置标题保留键盘折叠；静态标题没有交互反馈角色或焦点入口', async () => {
    const wrapper = mount(ConfigPanelSection, { props: { title: '数据源' } })
    const head = wrapper.get('.app-section-header')
    expect(head.attributes('aria-expanded')).toBe('true')
    await head.trigger('keydown', { key: 'Enter' })
    expect(head.attributes('aria-expanded')).toBe('false')
    await wrapper.setProps({ collapsible: false })
    expect(head.classes()).not.toContain('app-interaction-disclosure')
    expect(head.attributes('role')).toBeUndefined()
    expect(head.attributes('tabindex')).toBeUndefined()
    wrapper.unmount()
  })

  it('权限复选与折叠分离，原生触发器委托整行反馈，只读时仍能展开查看', async () => {
    const toggle = vi.fn()
    const wrapper = mount(PermissionTree, {
      props: {
        node: { key: 'research', label: '最新行情', kind: 'menu', nodeType: 'group', sysLocked: false },
        stateOf: () => 'off', toggle, readonly: false,
      },
      global: { plugins: [ElementPlus] },
    })
    const head = wrapper.get('.pt-group-head')
    const trigger = head.get('.app-section-header__trigger')
    expect(head.classes()).toContain('app-section-header')
    expect(head.attributes('role')).toBeUndefined()
    expect(trigger.element.tagName).toBe('BUTTON')
    await head.get('input[type="checkbox"]').setValue(true)
    expect(toggle).toHaveBeenCalledTimes(1)
    expect(trigger.attributes('aria-expanded')).toBe('true')
    await trigger.trigger('click')
    expect(trigger.attributes('aria-expanded')).toBe('false')
    expect(toggle).toHaveBeenCalledTimes(1)
    await wrapper.setProps({ readonly: true })
    expect(head.get('input').attributes('disabled')).toBeDefined()
    await trigger.trigger('click')
    expect(trigger.attributes('aria-expanded')).toBe('true')
    wrapper.unmount()
  })

  it('门禁拦截头部私有底色、触发器焦点和形态覆盖，允许业务布局', () => {
    const roles = designContracts.styleRoles.filter(role => role.className === 'app-section-header')
    expect(roles).toHaveLength(1)
    const fixture = (css: string) => `<template><div class="heading app-section-header"><button class="trigger app-section-header__trigger">标题</button></div></template><style scoped>${css}</style>`
    for (const css of ['.heading { background: var(--app-section-bg); }', '.trigger:focus-visible { outline: 1px solid red; }', '.heading { border-radius: 12px; }', '.heading::after { background: red; }']) {
      expect(auditSharedStyles([{ file: 'sample.vue', source: fixture(css) }], roles)).toHaveLength(1)
    }
    expect(auditSharedStyles([{ file: 'sample.vue', source: fixture('.heading { padding: 10px; }') }], roles)).toEqual([])
    for (const file of ['components/config/ConfigPanelSection.vue', 'components/SettingsGroup.vue', 'views/system/PermissionTree.vue']) {
      expect(readFileSync(resolve('src', file), 'utf8'), file).toContain('app-section-header')
    }
  })
})
