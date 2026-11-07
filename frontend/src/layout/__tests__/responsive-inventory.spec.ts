import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { PAGE_REGISTRY } from '../pageRegistry'
import { designSources } from '../../../scripts/design-source.mjs'
import { responsiveQueries, syncResponsiveInventory } from '../../../scripts/check-responsive-inventory.mjs'

const root = resolve(__dirname, '../../../..')
const inventory = readFileSync(resolve(root,
  'agent-works/configurable-layout-system/responsive-components.md'), 'utf8')
const start = '<!-- responsive-components:start -->'
const end = '<!-- responsive-components:end -->'
const table = '| 文件 | 查询原文（去重） | 行为 / 恢复入口 | 直接消费方 |\n|---|---|---|---|'
const sample = (rows = '') => `说明保持\n${start}\n\n${table}\n${rows}\n${end}\n尾部保持\n`
const source = (file = 'Probe.vue', css = '') => ({ file, source: `<template><div /></template><style>${css}</style>` })
const row = '| `frontend/src/Probe.vue` | 无自身 CSS 查询 | 委托宿主内滚，保留草稿。 | Parent |\n'

describe('响应式组件清单覆盖契约', () => {
  it('每个登记页面及登录页均有独立检查记录', () => {
    const report = readFileSync(resolve(root,
      'agent-works/configurable-layout-system/responsive-pages.md'), 'utf8')
    const recorded = report.split('\n').filter((line) => line.startsWith('| `/'))
      .map((line) => line.match(/^\| `([^`]+)`/)![1])
    expect(recorded.length).toBe(new Set(recorded).size)
    expect([...recorded].sort()).toEqual([...PAGE_REGISTRY.map((page) => page.path), '/login'].sort())
  })

  it('生产文件与 CSS 查询一致，人工说明不得留空或待补充', () => {
    expect(syncResponsiveInventory(inventory, designSources()).violations).toEqual([])
  })

  it('同步查询保留人工说明与表外内容，重复执行不改写', () => {
    const inputs = [source('Probe.vue', '@container pane (max-width: 720px) { div { display: block; } }')]
    const result = syncResponsiveInventory(sample(row), inputs)
    expect(result.violations).not.toEqual([])
    expect(result.document).toBe(sample(row.replace('无自身 CSS 查询', '`@container pane (max-width: 720px)`')))
    expect(syncResponsiveInventory(result.document, inputs)).toEqual({ document: result.document, violations: [] })
    expect(syncResponsiveInventory(result.document, [source()]).document).toBe(sample(row))
  })

  it('新增文件产生待补充项，删除文件移除旧登记，不伪造行为', () => {
    const result = syncResponsiveInventory(sample(row), [source('New.vue')])
    expect(result.document).not.toContain('frontend/src/Probe.vue')
    expect(result.document).toContain('frontend/src/New.vue')
    expect(result.document).toContain('待补充适配行为与恢复入口')
    expect(syncResponsiveInventory(result.document, [source('New.vue')]).violations).toHaveLength(1)
  })

  it('拒绝缺失/重复 marker、重复登记、坏行及空人工说明', () => {
    for (const document of ['正文', `${sample(row)}${start}`, `${end}${start}`, sample(row + row), sample('坏行\n')]) {
      expect(() => syncResponsiveInventory(document, [source()])).toThrow()
    }
    expect(() => syncResponsiveInventory(sample(row), [])).toThrow()
    expect(syncResponsiveInventory(sample(row.replace('委托宿主内滚，保留草稿。', '')), [source()]).violations).toHaveLength(1)
  })

  it('解析真实样式查询，忽略注释和脚本字符串并对多 style 去重', () => {
    const css = '@media (max-width: 720px) { div { color: red; } }'
    const input = `<script setup>const note = '@media (max-width: 1px) {}'</script>
      <template><div /></template><style>/* @media (max-width: 2px) {} */${css}</style>
      <style scoped>${css}@container pane (width < 600px) { div {} }</style>`
    expect(responsiveQueries('Probe.vue', input)).toEqual(['@media (max-width: 720px)', '@container pane (width < 600px)'])
    expect(() => responsiveQueries('Probe.vue', '<style>div {</style>')).toThrow()
  })
})
