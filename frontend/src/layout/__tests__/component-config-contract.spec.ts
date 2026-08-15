/**
 * 组件配置字段 + 页面业务偏好 注册完整性契约。
 *
 * 背景：一个字段要真正进入设置抽屉并持久化，必须同时挂多个分散注册点；漏任何一处都是
 * 静默失效（页面不报错、抽屉不出现该字段，或前端看似保存但后端 schema 拒绝）。
 * 本测试把「漏挂」从静默失效变成测试失败：
 *
 * A. pageRegistry.consumedComponentFields 登记的每个字段，必须在 COMPONENT_FIELD_DEFS 有定义；
 *    否则抽屉「组件设置」渲染不出该字段，且后端 schema 会拒收该字段的持久化（配置丢失）。
 * B. 凡提供 settings-drawer slot 的页面，其 supportsPageSettings 不得为 false（防止登记假抽屉入口）。
 * C. 前端 COMPONENT_FIELD_DEFS 与后端 COMPONENT_CONFIG_FIELDS_BY_KIND 字段口径一致；
 *    否则前端能配置但后端 schema 拒收，配置静默丢失。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { PAGE_REGISTRY } from '../pageRegistry'
import { getComponentFieldDef } from '../componentConfig'
import { COMPONENT_FIELD_DEFS } from '../componentConfig'

// 后端组件字段规则源（backend/storage/layout_config.py 的 COMPONENT_CONFIG_FIELDS_BY_KIND），
// 与前端 COMPONENT_FIELD_DEFS 必须同口径——否则前端能配置但后端 schema 拒收（配置静默丢失）。
const BACKEND_LAYOUT_CONFIG = readFileSync(
  new URL('../../../../backend/storage/layout_config.py', import.meta.url), 'utf-8',
)

describe('组件配置字段注册契约', () => {
  it('consumedComponentFields 每个字段都在 COMPONENT_FIELD_DEFS 有定义（否则抽屉不渲染且后端拒收）', () => {
    const missing: string[] = []
    for (const entry of PAGE_REGISTRY) {
      for (const [slotId, fields] of Object.entries(entry.consumedComponentFields ?? {})) {
        const slot = entry.layout.slots.find((s) => s.id === slotId)
        if (!slot) {
          missing.push(`${entry.pageKey}.${slotId} 未在 layout.slots 登记`)
          continue
        }
        for (const field of fields ?? []) {
          if (!getComponentFieldDef(slot.component, field)) {
            missing.push(`${entry.pageKey}.${slotId}.${field}（组件 ${slot.component}）缺 COMPONENT_FIELD_DEFS 定义`)
          }
        }
      }
    }
    expect(missing, `以下字段缺注册，会导致设置抽屉不渲染或后端拒绝持久化：\n${missing.join('\n')}`).toEqual([])
  })

  it('提供 settings-drawer slot 的页面 supportsPageSettings 不为 false（防假抽屉入口）', () => {
    const bad: string[] = []
    for (const entry of PAGE_REGISTRY) {
      const hasDrawer = entry.layout.slots.some((s) => s.component === 'settings-drawer')
      if (hasDrawer && entry.supportsPageSettings === false) {
        bad.push(entry.pageKey)
      }
    }
    expect(bad).toEqual([])
  })

  it('前端 COMPONENT_FIELD_DEFS 与后端 COMPONENT_CONFIG_FIELDS_BY_KIND 字段口径一致（防前端可配但后端拒收）', () => {
    // 只截取 COMPONENT_CONFIG_FIELDS_BY_KIND 字典块，避免对全文做正则（防回溯卡顿）。
    const start = BACKEND_LAYOUT_CONFIG.indexOf('COMPONENT_CONFIG_FIELDS_BY_KIND')
    const block = start >= 0 ? BACKEND_LAYOUT_CONFIG.slice(start, start + 2000) : ''
    // 某 kind 的字段集合文本：从 "kind": { 起到下一个顶层 "kind": 或块结束。
    const fieldsOfKind = (kind: string): string => {
      const marker = `"${kind}":`
      const i = block.indexOf(marker)
      if (i < 0) return ''
      const rest = block.slice(i + marker.length)
      const open = rest.indexOf('{')
      const close = rest.indexOf('}')
      return open >= 0 && close > open ? rest.slice(open + 1, close) : ''
    }
    const mismatches: string[] = []
    for (const [kind, defs] of Object.entries(COMPONENT_FIELD_DEFS)) {
      const backendFields = fieldsOfKind(kind)
      for (const def of defs ?? []) {
        if (!backendFields.includes(`"${def.key}"`)) {
          mismatches.push(`后端 ${kind} 缺字段 ${def.key}（前端已定义，后端 schema 会拒收该字段持久化）`)
        }
      }
    }
    expect(mismatches, `前后端字段口径不一致：\n${mismatches.join('\n')}`).toEqual([])
  })
})
