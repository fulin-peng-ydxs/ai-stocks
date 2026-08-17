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
 * C. 前端字段集合、类型、层级、通用边界及组件专属静态值域与后端双向一致；
 *    否则可能出现前端可配但后端拒收、后端私自放行，或同名字段值域互相污染。
 *
 * 注：pageSize 统一分页会话消费和页面不反写配置层的断言在 pageRegistry.spec.ts（复用其
 * sourceForPage 精确映射，避免按 slotId 全局 grep 把不同页面同名 slot 误配）。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { PAGE_REGISTRY } from '../pageRegistry'
import { getComponentFieldDef } from '../componentConfig'
import { COMPONENT_FIELD_DEFS } from '../componentConfig'
import { PAGE_SIZE_OPTIONS } from '@/constants/pagination'

// 后端组件字段规则源（backend/storage/layout_config.py 的 COMPONENT_CONFIG_FIELDS_BY_KIND），
// 与前端 COMPONENT_FIELD_DEFS 必须同口径——否则前端能配置但后端 schema 拒收（配置静默丢失）。
const BACKEND_LAYOUT_CONFIG = readFileSync(
  new URL('../../../../backend/storage/layout_config.py', import.meta.url), 'utf-8',
)

function pythonBlock(name: string): string {
  const start = BACKEND_LAYOUT_CONFIG.indexOf(`${name}:`)
  if (start < 0) return ''
  const open = BACKEND_LAYOUT_CONFIG.indexOf('{', start)
  const close = BACKEND_LAYOUT_CONFIG.indexOf('\n}\n', open)
  return open >= 0 && close > open ? BACKEND_LAYOUT_CONFIG.slice(open + 1, close) : ''
}

function quotedValues(source: string): string[] {
  return [...source.matchAll(/"([^"]+)"/g)].map((match) => match[1]!)
}

function backendFieldsByKind(): Record<string, string[]> {
  const result: Record<string, string[]> = {}
  for (const match of pythonBlock('COMPONENT_CONFIG_FIELDS_BY_KIND').matchAll(/^    "([^"]+)":\s*\{([^}]*)\},/gm)) {
    result[match[1]!] = quotedValues(match[2]!).sort()
  }
  return result
}

interface BackendFieldRule {
  type: string
  layers: string[]
  min?: number
  max?: number
}

function backendFieldRules(): Record<string, BackendFieldRule> {
  const result: Record<string, BackendFieldRule> = {}
  const block = pythonBlock('COMPONENT_CONFIG_FIELD_RULES')
  const starts = [...block.matchAll(/^    "([^"]+)":\s*\{/gm)]
  for (const [index, match] of starts.entries()) {
    const bodyStart = match.index! + match[0].length
    const bodyEnd = starts[index + 1]?.index ?? block.length
    const body = block.slice(bodyStart, bodyEnd)
    const type = /"type":\s*"([^"]+)"/.exec(body)?.[1]
    const layers = /"layers":\s*\{([^}]*)\}/.exec(body)?.[1]
    if (!type || layers == null) continue
    const min = /"min":\s*(\d+)/.exec(body)?.[1]
    const max = /"max":\s*(\d+)/.exec(body)?.[1]
    result[match[1]!] = {
      type,
      layers: quotedValues(layers).sort(),
      ...(min ? { min: Number(min) } : {}),
      ...(max ? { max: Number(max) } : {}),
    }
  }
  return result
}

function backendOptionsByKindField(): Record<string, string[]> {
  const result: Record<string, string[]> = {}
  const block = pythonBlock('COMPONENT_CONFIG_OPTIONS_BY_KIND_FIELD')
  for (const match of block.matchAll(/^    \("([^"]+)",\s*"([^"]+)"\):\s*\{([^}]*)\},/gm)) {
    result[`${match[1]}.${match[2]}`] = quotedValues(match[3]!).sort()
  }
  return result
}

function backendUserPersistenceByKindField(): Record<string, string> {
  const result: Record<string, string> = {}
  const block = pythonBlock('COMPONENT_CONFIG_USER_PERSISTENCE_BY_KIND_FIELD')
  for (const match of block.matchAll(/^    \("([^"]+)",\s*"([^"]+)"\):\s*"([^"]+)",/gm)) {
    result[`${match[1]}.${match[2]}`] = match[3]!
  }
  return result
}

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

  it('前后端组件种类与字段集合双向一致', () => {
    const frontend = Object.fromEntries(
      Object.entries(COMPONENT_FIELD_DEFS).map(([kind, defs]) => [
        kind,
        (defs ?? []).map((def) => def.key).sort(),
      ]),
    )
    expect(backendFieldsByKind()).toEqual(frontend)
  })

  it('前后端字段类型、层级和值域一致', () => {
    const controlType = {
      bool: 'bool',
      int: 'int',
      number: 'number',
      string: 'str',
      'string[]': 'str_list',
      enum: 'enum',
      object: 'object',
    } as const
    const frontendRules: Record<string, BackendFieldRule> = {}
    for (const defs of Object.values(COMPONENT_FIELD_DEFS)) {
      for (const def of defs ?? []) {
        const rule: BackendFieldRule = {
          type: controlType[def.control],
          layers: [...def.layers].sort(),
          ...(def.min != null ? { min: def.min } : {}),
          ...(def.max != null ? { max: def.max } : {}),
        }
        if (frontendRules[def.key]) {
          expect(rule, `前端同名字段 ${def.key} 在不同组件种类中规则不一致`).toEqual(frontendRules[def.key])
        } else {
          frontendRules[def.key] = rule
        }
      }
    }
    expect(backendFieldRules()).toEqual(frontendRules)
  })

  it('组件种类专属静态值域双向一致', () => {
    const frontendOptions: Record<string, string[]> = {}
    for (const [kind, defs] of Object.entries(COMPONENT_FIELD_DEFS)) {
      for (const def of defs ?? []) {
        if (def.options?.length) {
          frontendOptions[`${kind}.${def.key}`] = def.options.map(String).sort()
        }
      }
    }
    expect(backendOptionsByKindField()).toEqual(frontendOptions)
  })

  it('非布局 user 持久化目标前后端双向一致', () => {
    const frontendTargets: Record<string, string> = {}
    for (const [kind, defs] of Object.entries(COMPONENT_FIELD_DEFS)) {
      for (const def of defs ?? []) {
        if (def.userPersistence && def.userPersistence !== 'layout') {
          expect(def.layers).toContain('user')
          frontendTargets[`${kind}.${def.key}`] = def.userPersistence
        }
      }
    }
    expect(backendUserPersistenceByKindField()).toEqual(frontendTargets)
  })

  it('pageSize 上限与分页器可选值、后端校验一致', () => {
    const expectedMax = Math.max(...PAGE_SIZE_OPTIONS)
    for (const kind of ['data-table', 'wide-table'] as const) {
      const def = COMPONENT_FIELD_DEFS[kind]?.find((field) => field.key === 'pageSize')
      expect(def?.max, `${kind}.pageSize 上限必须等于分页器最大选项`).toBe(expectedMax)
    }
    expect(backendFieldRules().pageSize?.max, '后端 pageSize 校验上限必须与前端分页器一致').toBe(expectedMax)
  })
})
