/**
 * 页面注册表完整性（P0/P1）——保证 pageRegistry 作为单一事实源始终自洽：
 * 每个登记布局都过校验器、pageKey 自洽、无重复、editable 路径合法、getPageLayout 返回深拷贝。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { basename, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
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
const VIEWS_DIR = fileURLToPath(new URL('../../views/', import.meta.url))
const ROUTER_TS = readFileSync(new URL('../../router/index.ts', import.meta.url), 'utf-8')

interface RouteViewEntry {
  name: string
  path: string
  componentPath: string
  isPublic: boolean
}

function property(object: ts.ObjectLiteralExpression, name: string): ts.PropertyAssignment | undefined {
  return object.properties.find((item): item is ts.PropertyAssignment =>
    ts.isPropertyAssignment(item)
    && ((ts.isIdentifier(item.name) && item.name.text === name)
      || (ts.isStringLiteral(item.name) && item.name.text === name)))
}

function stringValue(object: ts.ObjectLiteralExpression, name: string): string | undefined {
  const initializer = property(object, name)?.initializer
  return initializer && ts.isStringLiteral(initializer) ? initializer.text : undefined
}

/** 提取 <script setup> 内容（与 runtimeComponentImports 同源正则）。 */
function scriptOf(source: string): string {
  return source.match(/<script\b[^>]*\bsetup\b[^>]*>([\s\S]*?)<\/script>/)?.[1] ?? source
}

/** 解包 `as const` 等后缀断言后，收集数组字面量的字符串元素。 */
function arrayLiteralStrings(initializer: ts.Expression | undefined): string[] {
  if (!initializer) return []
  let expr = initializer
  while (ts.isAsExpression(expr)) expr = expr.expression
  if (!ts.isArrayLiteralExpression(expr)) return []
  return expr.elements
    .filter((el): el is ts.StringLiteral => ts.isStringLiteral(el))
    .map((el) => el.text)
}

/**
 * 从页面脚本解析 useTableSort(slotId) 绑定的 allowedFields 白名单。
 * 返回白名单数组；找不到匹配调用点或白名单常量时返回 undefined。
 */
function whitelistForSlot(script: string, fileName: string, slotId: string): string[] | undefined {
  const sourceFile = ts.createSourceFile(fileName, script, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)

  const constArrays = new Map<string, string[]>()
  for (const statement of sourceFile.statements) {
    if (!ts.isVariableStatement(statement)) continue
    for (const declaration of statement.declarationList.declarations) {
      if (!ts.isIdentifier(declaration.name)) continue
      const values = arrayLiteralStrings(declaration.initializer)
      if (values.length) constArrays.set(declaration.name.text, values)
    }
  }

  let whitelistName: string | undefined
  const visit = (node: ts.Node): void => {
    if (whitelistName) return
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 'useTableSort') {
      const arg = node.arguments[0]
      if (arg && ts.isObjectLiteralExpression(arg)) {
        const slotProp = property(arg, 'slotId')?.initializer
        if (slotProp && ts.isStringLiteral(slotProp) && slotProp.text === slotId) {
          const af = property(arg, 'allowedFields')?.initializer
          if (af && ts.isIdentifier(af)) whitelistName = af.text
        }
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(sourceFile)

  if (!whitelistName) return undefined
  const values = constArrays.get(whitelistName)
  return values ? [...values] : undefined
}

/** StocksView 专用：收集模板中 `sortable="custom"` 列的 prop（原生 sortable 不在范围）。 */
function customSortableProps(source: string): string[] {
  const props: string[] = []
  for (const match of source.matchAll(/<AppTableColumn\b([^>]*)>/g)) {
    const attrs = match[1]
    if (!/\bsortable="custom"\b/.test(attrs)) continue
    const prop = /prop="([^"]+)"/.exec(attrs)?.[1]
    if (prop) props.push(prop)
  }
  return props
}

function routeViewEntries(source: string): RouteViewEntry[] {
  const sourceFile = ts.createSourceFile(
    'router.ts',
    source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TS,
  )
  const routesDeclaration = sourceFile.statements
    .filter(ts.isVariableStatement)
    .flatMap((statement) => statement.declarationList.declarations)
    .find((declaration) => ts.isIdentifier(declaration.name) && declaration.name.text === 'routes')
  const initializer = routesDeclaration?.initializer
  if (!initializer || !ts.isArrayLiteralExpression(initializer)) return []

  return initializer.elements.flatMap((element) => {
    if (!ts.isObjectLiteralExpression(element)) return []
    const name = stringValue(element, 'name')
    const path = stringValue(element, 'path')
    const component = property(element, 'component')?.initializer
    if (!name || !path || !component || !ts.isArrowFunction(component)) return []

    const body = component.body
    if (!ts.isCallExpression(body) || body.expression.kind !== ts.SyntaxKind.ImportKeyword) return []
    const argument = body.arguments[0]
    if (!argument || !ts.isStringLiteral(argument) || !argument.text.startsWith('@/views/')) return []

    const meta = property(element, 'meta')?.initializer
    const publicValue = meta && ts.isObjectLiteralExpression(meta)
      ? property(meta, 'public')?.initializer
      : undefined
    return [{
      name,
      path,
      componentPath: argument.text.slice(2),
      isPublic: publicValue?.kind === ts.SyntaxKind.TrueKeyword,
    }]
  })
}

const ROUTE_VIEWS = routeViewEntries(ROUTER_TS)
const ROUTE_COMPONENT_BY_NAME = new Map(
  ROUTE_VIEWS.map((entry) => [entry.name, entry.componentPath]),
)

function sourceForPage(pageKey: string): string {
  const componentPath = ROUTE_COMPONENT_BY_NAME.get(pageKey)
  if (!componentPath) return ''
  return readFileSync(new URL(`../../${componentPath}`, import.meta.url), 'utf-8')
}

function vueFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) return vueFiles(path)
    return entry.name.endsWith('.vue') ? [path] : []
  })
}

function coreComponentNames(markdown: string): Set<string> {
  const heading = /^核心真实复用组件清单：\s*$/m.exec(markdown)
  if (heading?.index == null) return new Set()
  const afterHeading = markdown.slice(heading.index + heading[0].length)
  const nextSection = /^核心 composable 复用清单：\s*$/m.exec(afterHeading)
  const table = nextSection?.index == null
    ? afterHeading
    : afterHeading.slice(0, nextSection.index)
  const names = new Set<string>()
  for (const line of table.split('\n')) {
    if (!line.startsWith('|')) continue
    const firstColumn = line.split('|')[1] ?? ''
    for (const match of firstColumn.matchAll(/`([^`]+)`/g)) names.add(match[1])
  }
  return names
}

function runtimeComponentImports(source: string, fileName = 'component.vue'): Set<string> {
  const script = source.match(/<script\b[^>]*\bsetup\b[^>]*>([\s\S]*?)<\/script>/)?.[1] ?? source
  const sourceFile = ts.createSourceFile(fileName, script, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
  const components = new Set<string>()

  for (const statement of sourceFile.statements) {
    if (!ts.isImportDeclaration(statement) || !ts.isStringLiteral(statement.moduleSpecifier)) continue
    const importPath = statement.moduleSpecifier.text
    if (
      !importPath.startsWith('@/components/')
      && !importPath.startsWith('@/layout/components/')
    ) continue
    const clause = statement.importClause
    if (!clause || clause.isTypeOnly) continue
    const namedDefault = clause.namedBindings && ts.isNamedImports(clause.namedBindings)
      ? clause.namedBindings.elements.some((element) =>
        !element.isTypeOnly
        && (element.propertyName?.text === 'default' || element.name.text === 'default'))
      : false
    if (!clause.name && !namedDefault) continue
    components.add(basename(importPath).replace(/\.vue$/, ''))
  }

  return components
}

const DESIGN_CORE_COMPONENTS = coreComponentNames(DESIGN_MD)
const DESIGN_PAGE_KEYS = new Set(
  DESIGN_PAGE_SECTION
    .split('\n')
    .map((line) => line.match(/^\|\s*`([^`]+)`\s*\|/)?.[1])
    .filter((value): value is string => Boolean(value && value !== 'pageKey')),
)

const SLOT_RUNTIME_COMPONENTS: Partial<Record<ComponentKind, string[]>> = {
  'data-table': ['AppDataTable', 'AppTableColumn'],
  'wide-table': ['AppDataTable', 'AppTableColumn'],
  'settings-drawer': ['PageSettingsDrawer'],
  'config-panel': ['ConfigGroupForm'],
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

  it('受控页面路由、pageRegistry 与页面源码保持双向一致', () => {
    const managedRoutes = ROUTE_VIEWS.filter((entry) => !entry.isPublic)
    expect(
      managedRoutes.map((entry) => entry.name).sort(),
      '所有非公开 View 路由都必须进入 pageRegistry',
    ).toEqual(PAGE_REGISTRY.map((entry) => entry.pageKey).sort())

    for (const entry of PAGE_REGISTRY) {
      const route = managedRoutes.find((item) => item.name === entry.pageKey)
      expect(route, `${entry.pageKey} 缺少同名受控路由`).toBeTruthy()
      expect(route?.path, `${entry.pageKey} 的 registry.path 与路由不一致`).toBe(entry.path)

      const source = sourceForPage(entry.pageKey)
      expect(source, `${entry.pageKey} 无法定位真实 Vue 页面`).not.toBe('')
      const imports = runtimeComponentImports(source, route?.componentPath)
      expect(imports.has('LayoutHost'), `${entry.pageKey} 必须导入 LayoutHost`).toBe(true)
      expect(source, `${entry.pageKey} 必须真实渲染 <LayoutHost>`).toContain('<LayoutHost')
      expect(source, `${entry.pageKey} 必须通过 getPageLayout 消费 registry 布局`).toContain('getPageLayout')
      expect(imports.has('AppStateBlock'), `${entry.pageKey} 必须复用 AppStateBlock 承接非 ready 状态`).toBe(true)
      expect(source, `${entry.pageKey} 必须真实渲染 <AppStateBlock>`).toContain('<AppStateBlock')
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

  it('DESIGN.md 页面 marker 与 pageRegistry 的 pageKey 精确一致', () => {
    expect([...DESIGN_PAGE_KEYS].sort()).toEqual(PAGE_REGISTRY.map((entry) => entry.pageKey).sort())
  })

  it('被两个以上页面消费的真实组件均登记到 DESIGN 核心清单', () => {
    const consumers = new Map<string, Set<string>>()
    for (const file of vueFiles(VIEWS_DIR)) {
      const source = readFileSync(file, 'utf8')
      for (const component of runtimeComponentImports(source, file)) {
        const pages = consumers.get(component) ?? new Set<string>()
        pages.add(file)
        consumers.set(component, pages)
      }
    }

    for (const [component, pages] of consumers) {
      if (pages.size < 2) continue
      expect(
        DESIGN_CORE_COMPONENTS.has(component),
        `${component} 已被 ${pages.size} 个页面消费但未登记到 DESIGN 核心组件清单`,
      ).toBe(true)
    }
  })

  it('组件消费解析支持混合、别名和多行 import，并忽略纯类型导入', () => {
    const components = runtimeComponentImports(`
      <script setup lang="ts">
      import ReplayChart,
        { type TradeMarker }
        from '@/components/CandleChart.vue'
      import { default as DrawerAlias } from '@/components/PageDrawer.vue'
      import LayoutAlias from '@/layout/components/LayoutHost.vue'
      import type { HelpTipProps } from '@/components/HelpTip.vue'
      </script>
    `)
    expect([...components].sort()).toEqual(['CandleChart', 'LayoutHost', 'PageDrawer'])
  })

  it('DESIGN 组件登记只读取核心真实复用组件表格第一列', () => {
    const components = coreComponentNames(`
核心真实复用组件清单：

| 真实组件 | 路径 |
|---|---|
| \`InsideTable\` / \`InsidePair\` | \`OutsidePathMention\` |

核心 composable 复用清单：

| Composable | 路径 |
|---|---|
| \`OutsideSection\` | x |
    `)
    expect([...components].sort()).toEqual(['InsidePair', 'InsideTable'])
  })

  it('只有真实消费个人设置的页面登记 settings-drawer，布局管理页显式排除', () => {
    const excluded = new Set(['layout-presets', 'layout-pages', 'layout-components'])
    expect(
      PAGE_REGISTRY.filter((entry) => entry.supportsPageSettings === false)
        .map((entry) => entry.pageKey)
        .sort(),
    ).toEqual([...excluded].sort())

    for (const entry of PAGE_REGISTRY) {
      const slot = entry.layout.slots.find((s) => s.id === 'settings')
      if (excluded.has(entry.pageKey)) {
        expect(slot, `${entry.pageKey} 不消费个人设置，不得登记假 settings slot`).toBeUndefined()
        expect(entry.consumedComponentFields?.settings).toBeUndefined()
        expect(entry.supportsComponentConfig).toBe(false)
        const source = sourceForPage(entry.pageKey)
        expect(source).not.toContain('PageSettingsTrigger')
        expect(source).not.toContain('PageSettingsDrawer')
        expect(source).not.toContain('useRemoteLayoutConfig')
        continue
      }
      expect(slot, `${entry.pageKey} 缺少 settings overlay slot`).toBeTruthy()
      expect(slot?.component).toBe('settings-drawer')
      expect(slot?.region).toBe('overlay')
      const source = sourceForPage(entry.pageKey)
      const imports = runtimeComponentImports(source)
      expect(imports.has('PageSettingsTrigger'), `${entry.pageKey} 必须导入 PageSettingsTrigger`).toBe(true)
      expect(imports.has('PageSettingsDrawer'), `${entry.pageKey} 必须导入 PageSettingsDrawer`).toBe(true)
      expect(source, `${entry.pageKey} 必须真实渲染页面设置入口`).toContain('<PageSettingsTrigger')
      expect(source, `${entry.pageKey} 必须真实渲染页面设置抽屉`).toContain('<PageSettingsDrawer')
    }
  })

  it('具有稳定真实实现的逻辑组件必须由页面实际消费对应组件', () => {
    for (const entry of PAGE_REGISTRY) {
      const source = sourceForPage(entry.pageKey)
      const imports = runtimeComponentImports(source)
      const kinds = new Set(entry.layout.slots.map((slot) => slot.component))
      for (const kind of kinds) {
        for (const component of SLOT_RUNTIME_COMPONENTS[kind] ?? []) {
          expect(
            imports.has(component),
            `${entry.pageKey} 声明 ${kind}，但未导入真实组件 ${component}`,
          ).toBe(true)
          expect(
            source.includes(`<${component}`),
            `${entry.pageKey} 声明 ${kind}，但未真实渲染 <${component}>`,
          ).toBe(true)
        }
      }
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

  it('独立详情行情统一消费 chart.minHeight，自适应工作台不机械套用固定高度', () => {
    const stockDetail = getPageEntry('stock-detail')!
    const sectorDetail = getPageEntry('sectors-detail')!
    const sectorWorkbench = getPageEntry('sectors')!

    expect(stockDetail.consumedComponentFields?.chart).toContain('minHeight')
    expect(stockDetail.layout.slots.find((slot) => slot.id === 'chart')).toMatchObject({
      component: 'chart',
      parentId: 'detail',
      config: { minHeight: 650 },
    })
    expect(sourceForPage('stock-detail')).toContain("componentValueOf('chart', 'minHeight')")

    expect(sectorDetail.consumedComponentFields?.chart).toContain('minHeight')
    expect(sectorDetail.layout.slots.find((slot) => slot.id === 'chart')).toMatchObject({
      component: 'chart',
      parentId: 'detail',
      config: { minHeight: 560 },
    })
    expect(sourceForPage('sectors-detail')).toContain("componentValueOf('chart', 'minHeight')")

    expect(sectorWorkbench.layout.slots.find((slot) => slot.id === 'chart')?.component).toBe('chart')
    expect(sectorWorkbench.consumedComponentFields?.chart ?? []).not.toContain('minHeight')
  })

  it('data-table / wide-table 必须消费并真实接入 border 页面级配置', () => {
    for (const entry of PAGE_REGISTRY) {
      const tableSlots = entry.layout.slots.filter((slot) => slot.component === 'data-table' || slot.component === 'wide-table')
      if (!tableSlots.length) continue
      const source = sourceForPage(entry.pageKey)
      expect(source, `${entry.pageKey} 使用表格组件但无法从 router 定位 Vue 页面源码`).not.toBe('')
      for (const slot of tableSlots) {
        expect(
          entry.consumedComponentFields?.[slot.id] ?? [],
          `${entry.pageKey}.${slot.id} 表格 slot 必须消费 border 配置`,
        ).toContain('border')
        expect(
          source.includes(`tableBorder('${slot.id}')`) || source.includes(`tableBorder("${slot.id}")`),
          `${entry.pageKey}.${slot.id} 表格 slot 必须真实传入 :border="tableBorder('${slot.id}')"`,
        ).toBe(true)
      }
    }
  })

  it('页面源码渲染受控组件时须登记对应 slot（反向契约，通用）', () => {
    // 反向契约：已登记的 slot 由正向测试校验字段接入；这里堵住「用了受控组件却未登记」——
    // 开放组件配置的页面，业务组件必须作为 slot 进入组件配置层（DESIGN §7.3 以 slot 登记为前提）。
    // 仅对「有唯一运行时组件、语义明确」的种类启用反向拦截：
    // - data-table/wide-table 共享 AppDataTable 运行时，渲染 AppDataTable 须有任一表格 slot
    //   （kind 属性区分两种，不要求同时登记）
    // - settings-drawer 由注册表自动注入 settings slot（injectSettingsDrawer），反向无意义
    // - config-panel / tabs 的运行时组件可出现在配置面板内部（ConfigGroupForm/el-tabs），
    //   无法区分「独立业务组件」与「面板内子结构」，反向判定会产生误报
    // 未来新增「有唯一运行时组件且需独立登记」的受控种类时，扩 REVERSE_CONTRACT_KINDS 即可。
    const REVERSE_CONTRACT_KINDS: { kinds: ComponentKind[]; runtimeNames: string[] }[] = [
      { kinds: ['data-table', 'wide-table'], runtimeNames: ['AppDataTable', 'AppTableColumn'] },
    ]
    for (const entry of PAGE_REGISTRY) {
      if (!entry.supportsComponentConfig) continue
      if (entry.pageKey.startsWith('config-')) continue  // config 共享视图，无法区分 tab 内结构
      const source = sourceForPage(entry.pageKey)
      if (!source) continue
      for (const { kinds, runtimeNames } of REVERSE_CONTRACT_KINDS) {
        const rendersRuntime = runtimeNames.some((name) => source.includes(name))
        if (!rendersRuntime) continue
        const hasSlot = entry.layout.slots.some((slot) => kinds.includes(slot.component as ComponentKind))
        expect(
          hasSlot,
          `${entry.pageKey} 渲染 <${runtimeNames[0]}> 但 layout 未登记 ${kinds.join('/')} slot——`
          + `开放组件配置的页面，业务组件必须登记为 slot（DESIGN §7.3）`,
        ).toBe(true)
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

  it('页面可排序列白名单与 sortFields 双向一致（列头能排序必须登记到抽屉候选）', () => {
    // 反向契约：设置抽屉「默认排序」下拉由 componentMeta.sortFields 驱动，页面列头可排序列白名单
    // （useTableSort 的 allowedFields / StocksView 的默认排序字段）必须与其双向一致。
    // 豁免：sortHasDirection:false 的模式枚举 slot（key 是排序模式不直接对列 prop）。
    const STOCKS_SORT_EXPECTATION: Record<string, string[]> = {
      table: ['pct_chg', 'close', 'code', 'name', 'industry'],
      groupTable: ['add_date', 'code', 'name', 'price', 'pct_chg', 'ret', 'last_date'],
    }

    for (const entry of PAGE_REGISTRY) {
      const sortableSlots = Object.entries(entry.componentMeta ?? {})
        .filter(([, meta]) => meta.sortFields?.length)
      if (!sortableSlots.length) continue

      const source = sourceForPage(entry.pageKey)
      expect(source, `${entry.pageKey} 声明 sortFields 但无法从 router 定位 Vue 页面源码`).not.toBe('')
      const script = scriptOf(source)

      for (const [slotId, meta] of sortableSlots) {
        if (meta.sortHasDirection === false) continue
        const sortKeys = (meta.sortFields ?? []).map((field) => field.key)

        if (entry.pageKey === 'stocks') {
          const expected = STOCKS_SORT_EXPECTATION[slotId]
          expect(expected, `stocks.${slotId} 缺少权威期望表登记`).toBeTruthy()
          expect(
            sortKeys.slice().sort(),
            `stocks.${slotId} sortFields 与权威期望表不一致`,
          ).toEqual([...expected].sort())
          continue
        }

        const whitelist = whitelistForSlot(script, `${entry.pageKey}.vue`, slotId)
        expect(
          whitelist,
          `${entry.pageKey}.${slotId} 声明 sortFields 但页面没有 useTableSort 白名单绑定（allowedFields）`,
        ).toBeTruthy()
        expect(
          whitelist!.slice().sort(),
          `${entry.pageKey}.${slotId} 页面可排序列白名单与 sortFields 双向漂移：列头可排序的字段必须登记到抽屉默认排序候选，反之亦然`,
        ).toEqual(sortKeys.slice().sort())
      }

      // stocks 兜底：任何 `sortable="custom"` 列都必须能在某个 slot 的 sortFields 里找到登记。
      if (entry.pageKey === 'stocks') {
        const registeredKeys = new Set(sortableSlots.flatMap(([, meta]) => (meta.sortFields ?? []).map((f) => f.key)))
        for (const prop of customSortableProps(source)) {
          expect(
            registeredKeys.has(prop),
            `stocks 列 prop="${prop}" 标记 sortable="custom" 但未登记到任何 slot 的 sortFields`,
          ).toBe(true)
        }
      }
    }
  })
})
