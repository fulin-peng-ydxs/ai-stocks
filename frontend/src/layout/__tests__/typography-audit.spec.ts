import { describe, expect, it } from 'vitest'
import { auditTypography, auditTypographyTree } from '../../../scripts/check-typography.mjs'

const tokens = { file: 'styles/global.css', source: `:root {
  --app-font-size-body: 14px; --app-font-size-caption: 12px;
  --app-font-weight-section: 600; --app-font-family-base: system-ui;
  --app-line-height-body: 22px; --app-space-3: 12px;
}` }
const audit = (source: string, file = 'views/Fixture.vue') => auditTypography([tokens, {
  file, source: source.includes('<template>') || source.includes('<script') ? source : '<template><span /></template>' + source,
}]).violations

describe('全站字体源码守卫', () => {
  it('扫描全部 Vue、CSS 和 TS 生产源码', () => {
    const result = auditTypographyTree()
    expect(result.files).toBeGreaterThan(300)
    expect(result.violations).toEqual([])
  })

  it('合法继承和共享 token 通过', () => {
    expect(audit('<style>.name {font:inherit; font-size:var(--app-font-size-body);font-weight:var(--app-font-weight-section)}</style>')).toEqual([])
  })

  it('变量拼写错误即使带 fallback 也不能静默通过', () => {
    expect(audit('<style>.name {font-size:var(--app-font-size-subtitle, 14px)}</style>').join()).toContain('未定义变量')
  })

  it('间距 token 不能冒充字号，字号也不能冒充字重', () => {
    expect(audit('<style>.name {font-size:var(--app-space-3);font-weight:var(--app-font-size-body)}</style>')).toHaveLength(2)
  })

  it.each([
    '<template><span :style="{fontWeight: 600}">名称</span></template>',
    '<template><span :style="{fontSize: `14px`}">名称</span></template>',
    '<template><span style="font-size:14px">名称</span></template>',
    '<script setup>const option = { fontSize: 14 }</script>',
    '<script setup>const option = { ["fontSize"]: 14 }</script>',
    '<script setup>const style = {"font-size": "14px"}</script>',
    '<script setup>const fontWeight = 650; const style = { fontWeight }</script>',
    '<script setup>const typography = {body:17}; const option = {fontSize:typography.body}</script>',
    '<template><svg><text font-size="14">文字</text></svg></template>',
    '<script setup>const html = `<div style="font-size:14px">值</div>`</script>',
    '<script setup>element.style.fontSize = size</script>',
    '<style>.name {font:600 14px system-ui}</style>',
  ])('拦截模板、脚本、HTML 字符串及简写中的私有字体: %s', source => {
    expect(audit(source).length).toBeGreaterThan(0)
  })

  it('品牌例外不能泄漏到普通登录按钮，也不能任意更改例外值', () => {
    expect(audit('<style>.login-card-title h2 {font-size:29px}</style>', 'views/LoginView.vue')).toEqual([])
    expect(audit('<style>.login-primary {font-weight:650}</style>', 'views/LoginView.vue')).toHaveLength(1)
    expect(audit('<style>.login-card-title h2 {font-size:31px}</style>', 'views/LoginView.vue')).toHaveLength(1)
  })

  it('局部变量不能建立新的字体尺度', () => {
    expect(audit('<style>.name {--local-font-size:17px;font-size:var(--local-font-size)}</style>').join()).toContain('共享事实源')
    expect(audit('<style>.name {--size:calc(var(--app-font-size-body) + 3px);font-size:var(--size)}</style>').join()).toContain('有效字体角色')
  })

  it.each(['calc(var(--app-font-size-body) + 3px)', 'var(--app-font-size-body, 17px)', 'var(--app-font-size-body) 17px'])('合法 token 不能掩盖私有尺度: %s', value => {
    expect(audit(`<style>.name {font-size:${value}}</style>`).length).toBeGreaterThan(0)
  })

  it('图表适配器中的拼错 token 也会失败', () => {
    expect(audit('<script setup>const size = numberToken("--app-font-size-missing", 12)</script>').join()).toContain('未定义变量')
  })

  it('数字强调不能把其他合法字重 token 拼成私有配方', () => {
    expect(auditTypography([tokens, {file:'components/Fixture.vue',source:'<template><span /></template><style>.metric {font-size:var(--app-font-size-data);font-weight:var(--app-font-weight-regular)}</style>'}]).violations.join()).toContain('完整消费')
  })

  it('根字体 token 自引用不能绕过循环检测', () => {
    expect(auditTypography([{file:'styles/global.css',source:':root {--app-font-size-body:var(--app-font-size-body)} .name {font-size:var(--app-font-size-body)}'}]).violations.join()).toContain('有效字体角色')
  })

  it('循环别名和损坏的别名不放过', () => {
    expect(audit('<style>.name {--a:var(--b);--b:var(--a);font-size:var(--a)}</style>').join()).toContain('有效字体角色')
  })
})
