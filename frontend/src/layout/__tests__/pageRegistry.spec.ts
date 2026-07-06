/**
 * 页面注册表完整性（P0/P1）——保证 pageRegistry 作为单一事实源始终自洽：
 * 每个登记布局都过校验器、pageKey 自洽、无重复、editable 路径合法、getPageLayout 返回深拷贝。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { PAGE_REGISTRY, getPageEntry, getPageLayout, listComponentUsage, listManagedPages } from '../pageRegistry'
import { validateLayout } from '../validator'
import { COMPONENT_CATALOG } from '../components'
import { getComponentFieldDef } from '../componentConfig'
import type { ComponentKind } from '../schema'

const RESPONSIVE_PROFILES = new Set(['single-column', 'safe-reflow', 'mixed-panel'])
const DESIGN_MD = readFileSync(new URL('../../../../DESIGN.md', import.meta.url), 'utf-8')
const DESIGN_PAGE_SECTION = DESIGN_MD.match(
  /<!-- page-registry:start -->([\s\S]*?)<!-- page-registry:end -->/,
)?.[1] ?? ''
const ROUTER_TS = readFileSync(new URL('../../router/index.ts', import.meta.url), 'utf-8')
const ROUTE_COMPONENT_BY_NAME = new Map<string, string>()
for (const match of ROUTER_TS.matchAll(/name:\s*'([^']+)'[^}]*component:\s*\(\)\s*=>\s*import\('@\/([^']+)'\)/g)) {
  ROUTE_COMPONENT_BY_NAME.set(match[1], match[2])
}

function sourceForPage(pageKey: string): string {
  const componentPath = ROUTE_COMPONENT_BY_NAME.get(pageKey)
  if (!componentPath) return ''
  return readFileSync(new URL(`../../${componentPath}`, import.meta.url), 'utf-8')
}

describe('页面注册表完整性', () => {
  it('注册表非空且与 listManagedPages 一致', () => {
    expect(PAGE_REGISTRY.length).toBeGreaterThan(0)
    expect(listManagedPages()).toEqual(PAGE_REGISTRY)
  })

  it('pageKey 唯一且与各自布局自洽', () => {
    const keys = PAGE_REGISTRY.map((e) => e.pageKey)
    expect(new Set(keys).size).toBe(keys.length)
    for (const entry of PAGE_REGISTRY) {
      expect(entry.layout.pageKey).toBe(entry.pageKey)
      expect(entry.layout.archetype).toBe(entry.archetype)
      expect(RESPONSIVE_PROFILES.has(entry.responsiveProfile)).toBe(true)
    }
  })

  it('每个登记布局都通过校验器（无 error 级问题）', () => {
    for (const entry of PAGE_REGISTRY) {
      const errors = validateLayout(entry.layout).filter((i) => i.level === 'error')
      expect(errors, `${entry.pageKey} 布局违规: ${errors.map((e) => e.message).join('; ')}`).toEqual([])
    }
  })

  it('editable 旋钮 path 必须指向 density 或真实存在的 slot 字段', () => {
    for (const entry of PAGE_REGISTRY) {
      const slotIds = new Set(entry.layout.slots.map((s) => s.id))
      for (const knob of entry.layout.editable) {
        if (knob.path === 'density') continue
        const parts = knob.path.split('.')
        expect(parts[0], `${entry.pageKey} 非法旋钮路径 ${knob.path}`).toBe('slots')
        expect(slotIds.has(parts[1]), `${entry.pageKey} 旋钮 ${knob.path} 指向不存在的 slot`).toBe(true)
      }
    }
  })

  it('getPageLayout 返回深拷贝，改写不污染注册表', () => {
    const entry = PAGE_REGISTRY[0]
    const a = getPageLayout(entry.pageKey)
    a.density = 'compact'
    a.slots[0].order = 999
    const b = getPageLayout(entry.pageKey)
    expect(b.density).toBe(entry.layout.density)
    expect(b.slots[0].order).toBe(entry.layout.slots[0].order)
  })

  it('getPageEntry 未登记页返回 undefined，getPageLayout 抛错', () => {
    expect(getPageEntry('not-a-page')).toBeUndefined()
    expect(() => getPageLayout('not-a-page')).toThrow()
  })

  it('配置管理拆页后只登记四个子页面，不保留旧 config 页', () => {
    expect(getPageEntry('config')).toBeUndefined()
    expect(() => getPageLayout('config')).toThrow()
    expect(PAGE_REGISTRY.filter((entry) => entry.path.startsWith('/system/config/')).map((entry) => entry.pageKey).sort())
      .toEqual(['config-score', 'config-system', 'config-tech', 'config-trade'])
  })

  it('阶段五平台能力页已登记到布局系统', () => {
    expect(getPageEntry('audit-log')?.path).toBe('/system/audit')
    expect(getPageEntry('audit-log')?.archetype).toBe('list')
    expect(getPageLayout('audit-log').slots.map((slot) => slot.id)).toEqual(
      expect.arrayContaining(['toolbar', 'summary', 'filters', 'auditTable']),
    )

    expect(getPageEntry('data-dictionary')?.path).toBe('/system/dicts')
    expect(getPageEntry('data-dictionary')?.archetype).toBe('master-detail')
    expect(getPageLayout('data-dictionary').slots.map((slot) => slot.id)).toEqual(
      expect.arrayContaining(['toolbar', 'workspace', 'typeDialog', 'itemDialog', 'deleteConfirm']),
    )
  })

  it('每个 registry 页面都已登记到 DESIGN.md 页面登记区块', () => {
    for (const entry of PAGE_REGISTRY) {
      expect(DESIGN_PAGE_SECTION, `${entry.pageKey}(${entry.label}) 未出现在 DESIGN.md 页面登记区块`).toContain(entry.label)
    }
  })

  it('每个 registry 页面都有 settings-drawer overlay slot', () => {
    for (const entry of PAGE_REGISTRY) {
      const slot = entry.layout.slots.find((s) => s.id === 'settings')
      expect(slot, `${entry.pageKey} 缺少 settings overlay slot`).toBeTruthy()
      expect(slot?.component).toBe('settings-drawer')
      expect(slot?.region).toBe('overlay')
    }
  })
})

// P4「系统组件」工作区依赖：组件消费关系查询 + 组件配置登记一致性。
describe('组件消费关系与配置一致性（P4）', () => {
  it('listComponentUsage 命中真实消费页面，未消费组件返回空', () => {
    const tableUsers = listComponentUsage('data-table').map((u) => u.pageKey)
    expect(tableUsers).toEqual(expect.arrayContaining(['board', 'screen', 'stocks', 'data-quality']))
    expect(listComponentUsage('tabs').map((u) => u.pageKey)).not.toContain('config-score')
    // 目录中存在但无页面消费的组件（如 kanban）应返回空数组而非报错。
    expect(listComponentUsage('kanban')).toEqual([])
  })

  it('listComponentUsage 对目录里每个组件种类都可安全调用', () => {
    for (const kind of Object.keys(COMPONENT_CATALOG) as ComponentKind[]) {
      const usage = listComponentUsage(kind)
      for (const u of usage) {
        const entry = getPageEntry(u.pageKey)
        expect(entry, `${kind} 消费页 ${u.pageKey} 未登记`).toBeTruthy()
        expect(entry!.layout.slots.some((s) => s.id === u.slotId && s.component === kind)).toBe(true)
      }
    }
  })

  it('consumedComponentFields 登记必须指向真实 slot 且字段已在 componentConfig 登记', () => {
    for (const entry of PAGE_REGISTRY) {
      const consumed = entry.consumedComponentFields
      if (!consumed) {
        // 未声明消费字段的页面不应标 supportsComponentConfig（避免配置中心渲染空块）。
        if (entry.supportsComponentConfig) {
          expect.fail(`${entry.pageKey} 标记 supportsComponentConfig 但无 consumedComponentFields`)
        }
        continue
      }
      for (const [slotId, fields] of Object.entries(consumed)) {
        const slot = entry.layout.slots.find((s) => s.id === slotId)
        expect(slot, `${entry.pageKey} consumed slot ${slotId} 不存在`).toBeTruthy()
        for (const field of fields) {
          expect(
            getComponentFieldDef(slot!.component, field),
            `${entry.pageKey}.${slotId}.${field} 未在 componentConfig 登记`,
          ).toBeTruthy()
        }
      }
    }
  })

  it('可交互排序字段必须进入 defaultSort 配置闭环', () => {
    for (const entry of PAGE_REGISTRY) {
      for (const [slotId, meta] of Object.entries(entry.componentMeta ?? {})) {
        if (!meta.sortFields?.length) continue

        const consumed = entry.consumedComponentFields?.[slotId] ?? []
        expect(
          consumed,
          `${entry.pageKey}.${slotId} 声明 sortFields 后必须消费 defaultSort，保证列头排序和设置抽屉默认排序同源`,
        ).toContain('defaultSort')

        const defaultSort = entry.layout.slots.find((slot) => slot.id === slotId)?.config?.defaultSort
        if (defaultSort == null) continue
        const defaultSortField = String(defaultSort).split(':')[0]
        const sortKeys = meta.sortFields.map((field) => field.key)
        expect(
          sortKeys,
          `${entry.pageKey}.${slotId} 默认排序 ${String(defaultSort)} 必须来自 componentMeta.sortFields`,
        ).toContain(defaultSortField)
      }
    }
  })

  it('声明 sortFields 的页面源码必须接入列头排序并回写 defaultSort', () => {
    for (const entry of PAGE_REGISTRY) {
      const sortableSlots = Object.entries(entry.componentMeta ?? {}).filter(([, meta]) => meta.sortFields?.length)
      if (!sortableSlots.length) continue

      const source = sourceForPage(entry.pageKey)
      expect(source, `${entry.pageKey} 声明 sortFields 但无法从 router 定位 Vue 页面源码`).not.toBe('')
      expect(source, `${entry.pageKey} 声明 sortFields 后页面必须接入 @sort-change`).toContain('@sort-change')

      for (const [slotId, meta] of sortableSlots) {
        const writesDefaultSort =
          source.includes(`setComponentKnob('${slotId}', 'defaultSort'`) ||
          source.includes(`setComponentKnob("${slotId}", "defaultSort"`) ||
          (source.includes('useTableSort') && source.includes(`slotId: '${slotId}'`)) ||
          (source.includes('useTableSort') && source.includes(`slotId: "${slotId}"`))
        expect(
          writesDefaultSort,
          `${entry.pageKey}.${slotId} 声明 sortFields 后页面列头排序必须回写 slots.${slotId}.config.defaultSort`,
        ).toBe(true)

        for (const field of meta.sortFields ?? []) {
          expect(
            source,
            `${entry.pageKey}.${slotId} sortFields.${field.key} 未在页面源码中出现，可能只是抽屉候选但表头不可操作`,
          ).toContain(field.key)
        }
      }
    }
  })
})
