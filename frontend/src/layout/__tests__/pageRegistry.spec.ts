/**
 * 页面注册表完整性（P0/P1）——保证 pageRegistry 作为单一事实源始终自洽：
 * 每个登记布局都过校验器、pageKey 自洽、无重复、editable 路径合法、getPageLayout 返回深拷贝。
 */
import { describe, expect, it } from 'vitest'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { basename, extname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
import {
  PAGE_REGISTRY,
  applicableComponentFields,
  componentMetaForSlot,
  getPageEntry,
  getPageLayout,
  listComponentUsage,
  listManagedPages,
} from '../pageRegistry'
import { validateLayout } from '../validator'
import { COMPONENT_CATALOG } from '../components'
import { getComponentFieldDef } from '../componentConfig'
import type { ComponentKind } from '../schema'
import { MARKET_WORKSPACE_MIN_HEIGHT } from '../marketWorkspaceSizing'
import { COMPOSITE_COMPONENT_CONTRACTS } from '../compositeComponentContracts'
import { PAGE_BUSINESS_PREFERENCE_CONTRACTS } from '../pageBusinessPreferenceContracts'

const RESPONSIVE_PROFILES = new Set(['single-column', 'safe-reflow', 'mixed-panel'])
const DESIGN_MD = readFileSync(new URL('../../../../DESIGN.md', import.meta.url), 'utf-8')
const DESIGN_PAGE_SECTION = DESIGN_MD.match(
  /<!-- page-registry:start -->([\s\S]*?)<!-- page-registry:end -->/,
)?.[1] ?? ''
const VIEWS_DIR = fileURLToPath(new URL('../../views/', import.meta.url))
const COMPONENTS_DIR = fileURLToPath(new URL('../../components/', import.meta.url))
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

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
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

/** 收集页面真实用于列显隐判断的 key，避免 componentMeta 只生成设置项却没有业务渲染消费。 */
function configurableColumnVisibilityKeys(source: string): Set<string> {
  const keys = new Set<string>()
  for (const match of source.matchAll(/\b[A-Za-z_$][\w$]*Visible\(\s*['"]([^'"]+)['"]\s*\)/g)) {
    keys.add(match[1]!)
  }
  return keys
}

const RELATED_BOARD_COLUMNS = new Set([
  'board.table.relatedIndustry',
  'board.table.relatedConcept',
  'screen.result.relatedIndustry',
  'screen.result.relatedConcept',
  'stocks.table.relatedIndustry',
  'stocks.table.relatedConcept',
  'stocks.groupTable.relatedIndustry',
  'stocks.groupTable.relatedConcept',
])

/** 对象字面量的顶层属性名（不展开嵌套对象/数组的子 key）。 */
function topLevelKeys(object: ts.ObjectLiteralExpression): string[] {
  return object.properties
    .filter((p): p is ts.PropertyAssignment => ts.isPropertyAssignment(p))
    .map((p) => (ts.isIdentifier(p.name) || ts.isStringLiteral(p.name) ? p.name.text : ''))
    .filter(Boolean)
}

/**
 * 解析页面 usePageSettings 的业务偏好 defaults 顶层字段及历史 settings 别名。
 * defaults 可能是内联对象字面量或 const 引用。
 */
function pageSettingsFields(source: string, fileName: string): { fields: string[]; aliases: string[] } {
  const script = scriptOf(source)
  const sourceFile = ts.createSourceFile(fileName, script, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)

  // const 声明的对象字面量索引（供 defaults 用标识符引用时回溯）
  const constObjects = new Map<string, ts.ObjectLiteralExpression>()
  for (const statement of sourceFile.statements) {
    if (!ts.isVariableStatement(statement)) continue
    for (const declaration of statement.declarationList.declarations) {
      if (!ts.isIdentifier(declaration.name)) continue
      const init = declaration.initializer
      if (init && ts.isObjectLiteralExpression(init)) constObjects.set(declaration.name.text, init)
    }
  }

  let fields: string[] = []
  const aliases = new Set<string>(['settings'])
  const visit = (node: ts.Node): void => {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 'usePageSettings') {
      const arg = node.arguments[1]
      if (arg) {
        if (ts.isObjectLiteralExpression(arg)) fields = topLevelKeys(arg)
        else if (ts.isIdentifier(arg)) {
          const resolved = constObjects.get(arg.text)
          if (resolved) fields = topLevelKeys(resolved)
        }
      }
      // 兼容识别历史解构别名，供契约测试输出准确违规字段。
      if (ts.isVariableDeclaration(node.parent) && ts.isObjectBindingPattern(node.parent.name)) {
        for (const el of node.parent.name.elements) {
          if (ts.isIdentifier(el.name) && el.propertyName && ts.isIdentifier(el.propertyName) && el.propertyName.text === 'settings') {
            aliases.add(el.name.text)
          }
        }
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(sourceFile)
  return { fields, aliases: [...aliases] }
}

/** 设置抽屉业务段内通过可写 computed 间接编辑的持久化字段。 */
function computedPageSettingsFieldsInBusiness(
  source: string,
  fileName: string,
  aliases: string[],
  business: string,
): Set<string> {
  const sourceFile = ts.createSourceFile(fileName, scriptOf(source), ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
  const result = new Set<string>()
  for (const statement of sourceFile.statements) {
    if (!ts.isVariableStatement(statement)) continue
    for (const declaration of statement.declarationList.declarations) {
      if (!ts.isIdentifier(declaration.name) || !declaration.initializer) continue
      const model = declaration.name.text
      if (!new RegExp(`v-model(?:[:.][^=\\s]+)*\\s*=\\s*["']${model}["']`).test(business)) continue
      const visit = (node: ts.Node): void => {
        if (
          ts.isBinaryExpression(node)
          && node.operatorToken.kind === ts.SyntaxKind.EqualsToken
          && ts.isPropertyAccessExpression(node.left)
          && ts.isIdentifier(node.left.expression)
          && aliases.includes(node.left.expression.text)
        ) {
          result.add(node.left.name.text)
        }
        ts.forEachChild(node, visit)
      }
      visit(declaration.initializer)
    }
  }
  return result
}

/** 找出页面脚本对 useRemoteLayoutConfig 返回写方法的真实调用，覆盖解构别名和对象属性调用。 */
function directComponentKnobWrites(source: string, fileName: string): string[] {
  const sourceFile = ts.createSourceFile(fileName, scriptOf(source), ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
  const writerAliases = new Set<string>()
  const configObjects = new Set<string>()
  const calls: string[] = []

  const collectBindings = (node: ts.Node): void => {
    if (
      ts.isVariableDeclaration(node)
      && node.initializer
      && ts.isCallExpression(node.initializer)
      && ts.isIdentifier(node.initializer.expression)
      && node.initializer.expression.text === 'useRemoteLayoutConfig'
    ) {
      if (ts.isIdentifier(node.name)) configObjects.add(node.name.text)
      if (ts.isObjectBindingPattern(node.name)) {
        for (const element of node.name.elements) {
          if (!ts.isIdentifier(element.name)) continue
          const exported = element.propertyName && ts.isIdentifier(element.propertyName)
            ? element.propertyName.text
            : element.name.text
          if (exported === 'setComponentKnob') writerAliases.add(element.name.text)
        }
      }
    }
    ts.forEachChild(node, collectBindings)
  }
  collectBindings(sourceFile)

  const collectCalls = (node: ts.Node): void => {
    if (ts.isCallExpression(node)) {
      if (ts.isIdentifier(node.expression) && writerAliases.has(node.expression.text)) {
        calls.push(node.expression.text)
      }
      if (
        ts.isPropertyAccessExpression(node.expression)
        && ts.isIdentifier(node.expression.expression)
        && configObjects.has(node.expression.expression.text)
        && node.expression.name.text === 'setComponentKnob'
      ) {
        calls.push(node.expression.getText(sourceFile))
      }
    }
    ts.forEachChild(node, collectCalls)
  }
  collectCalls(sourceFile)
  return calls
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

/**
 * 页面通过业务子组件消费布局组件同样属于真实消费；递归收集静态 Vue 组件树，
 * 避免为了满足契约而在路由页保留无用的直接导入。
 */
function sourceTreeForPage(pageKey: string): string {
  const entryPath = ROUTE_COMPONENT_BY_NAME.get(pageKey)
  if (!entryPath) return ''
  const visited = new Set<string>()
  const sources: string[] = []

  const visit = (componentPath: string): void => {
    if (visited.has(componentPath)) return
    visited.add(componentPath)
    const source = readFileSync(new URL(`../../${componentPath}`, import.meta.url), 'utf-8')
    sources.push(source)
    for (const match of source.matchAll(/import\s+\w+\s+from\s+['"]@\/((?:views|components|layout\/components)\/[^'"]+\.vue)['"]/g)) {
      visit(match[1]!)
    }
  }

  visit(entryPath)
  return `<script setup>${sources.map(scriptOf).join('\n')}</script>\n${sources.join('\n')}`
}

function vueFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) return vueFiles(path)
    return entry.name.endsWith('.vue') ? [path] : []
  })
}

interface CoreComponentRow {
  names: string[]
  paths: string[]
}

function coreComponentRows(markdown: string): CoreComponentRow[] {
  const heading = /^核心真实复用组件清单：\s*$/m.exec(markdown)
  if (heading?.index == null) return []
  const afterHeading = markdown.slice(heading.index + heading[0].length)
  const lines = afterHeading.split('\n')
  const tableStart = lines.findIndex((line) => line.trimStart().startsWith('|'))
  if (tableStart < 0) return []
  const rows: CoreComponentRow[] = []
  for (const line of lines.slice(tableStart)) {
    if (!line.trimStart().startsWith('|')) break
    const columns = line.split('|')
    const names = [...(columns[1] ?? '').matchAll(/`([^`]+)`/g)].map((match) => match[1]!)
    const paths = [...(columns[2] ?? '').matchAll(/`([^`]+)`/g)].map((match) => match[1]!)
    if (names.length) rows.push({ names, paths })
  }
  return rows
}

function coreComponentNames(markdown: string): Set<string> {
  return new Set(coreComponentRows(markdown).flatMap((row) => row.names))
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
const DESIGN_PAGE_KEY_ROWS = DESIGN_PAGE_SECTION
  .split('\n')
  .map((line) => line.match(/^\|\s*`([^`]+)`\s*\|/)?.[1])
  .filter((value): value is string => Boolean(value && value !== 'pageKey'))
const DESIGN_PAGE_KEYS = new Set(DESIGN_PAGE_KEY_ROWS)

function designPageRows(): Map<string, { archetype: string; components: string[] }> {
  const rows = new Map<string, { archetype: string; components: string[] }>()
  for (const line of DESIGN_PAGE_SECTION.split('\n')) {
    const columns = line.split('|')
    const pageKey = /`([^`]+)`/.exec(columns[1] ?? '')?.[1]
    const archetype = /`([^`]+)`/.exec(columns[3] ?? '')?.[1]
    if (!pageKey || !archetype || pageKey === 'pageKey') continue
    const components = [...(columns[5] ?? '').matchAll(/(?:action|main|nested|overlay):`([^`]+)`/g)]
      .map((match) => match[1]!.replace(/\(growMain\)$/, ''))
    rows.set(pageKey, { archetype, components })
  }
  return rows
}

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

  it('交易纪律工作台登记唯一成长页签、三个业务面板和受控历史配置', () => {
    const entry = getPageEntry('trade-discipline')!
    const slots = entry.layout.slots
    expect(slots.filter((slot) => slot.growMain).map((slot) => slot.id)).toEqual([
      'workspaceTabs',
    ])
    expect(slots.filter((slot) => slot.parentId === 'workspaceTabs').map((slot) => slot.id))
      .toEqual(['checkinPanel', 'rulesPanel', 'history', 'historyFilters'])
    expect(applicableComponentFields(entry, 'history').map((field) => field.key)).toEqual([
      'border', 'pageSize', 'defaultSort', 'hiddenColumns',
    ])
    expect(entry.componentMeta?.history?.sortFields).toEqual([
      { key: 'trade_date', label: '交易日' },
    ])
    expect(entry.componentMeta?.history?.columns?.map((column) => column.key)).toEqual([
      'trade_date', 'rule_name', 'assessment', 'operation_count',
      'reason_name_snapshot', 'current_revision_no', 'updated_at',
    ])
    expect(entry.componentMeta?.history?.tabs).toBeUndefined()
    expect(JSON.stringify(entry)).not.toContain('defaultActive')

    const view = sourceForPage('trade-discipline')
    const history = readFileSync(join(VIEWS_DIR, 'trade-discipline/components/TradeDisciplineHistory.vue'), 'utf-8')
    const drawer = readFileSync(join(VIEWS_DIR, 'trade-discipline/components/TradeCheckinRevisionDrawer.vue'), 'utf-8')
    expect(`${view}\n${history}\n${drawer}`).not.toMatch(/<el-(?:table|drawer)\b/i)
    expect(history).toContain('<AppDataTable')
    expect(drawer).toContain('<AppDetailDrawer')
  })

  it('数据采集将任务中心与采集日志登记为同一成长页签的两个面板', () => {
    const entry = getPageEntry('data-ingest')!
    const workspace = entry.layout.slots.find((slot) => slot.id === 'workspace')

    expect(workspace).toMatchObject({ component: 'tabs', growMain: true })
    expect(workspace?.parentId).toBeUndefined()
    expect(entry.componentMeta?.workspace?.tabs).toEqual([
      { key: 'tasks', label: '任务中心' },
      { key: 'logs', label: '采集日志' },
    ])
    expect(entry.layout.slots.filter((slot) => slot.parentId === 'workspace').map((slot) => slot.id))
      .toEqual(['taskTable', 'logTable'])
    expect(entry.layout.slots.filter((slot) => slot.region === 'overlay').map((slot) => slot.id))
      .toEqual(['ingestExecutionDialog', 'resultMaintenanceDialog', 'taskLogDrawer', 'settings'])
  })

  it('登记列元数据的列表组件自动继承通用列显隐能力', () => {
    for (const entry of PAGE_REGISTRY) {
      for (const [slotId, meta] of Object.entries(entry.componentMeta ?? {})) {
        if (!meta.columns?.length) continue
        const slot = entry.layout.slots.find((candidate) => candidate.id === slotId)
        if (!slot || !['data-table', 'wide-table'].includes(slot.component)) continue
        expect(applicableComponentFields(entry, slotId).map((field) => field.key)).toContain('hiddenColumns')
      }
    }
  })

  it('DESIGN 页面登记 marker 不得出现重复 pageKey', () => {
    expect(DESIGN_PAGE_KEYS.size, '重复 pageKey 会被 Set 吞掉，导致双向一致性测试假通过')
      .toBe(DESIGN_PAGE_KEY_ROWS.length)
  })

  it('DESIGN 页面索引中的原型和组件摘要与 pageRegistry 一致', () => {
    const rows = designPageRows()
    const errors: string[] = []
    for (const entry of PAGE_REGISTRY) {
      const row = rows.get(entry.pageKey)
      if (row?.archetype !== entry.archetype) {
        errors.push(`${entry.pageKey} 原型: DESIGN=${row?.archetype} registry=${entry.archetype}`)
      }
      const registered = entry.layout.slots
        .filter((slot) => slot.component !== 'settings-drawer')
        .map((slot) => slot.component)
        .sort()
      const documented = [...(row?.components ?? [])].sort()
      if (JSON.stringify(documented) !== JSON.stringify(registered)) {
        errors.push(`${entry.pageKey} 组件: DESIGN=${documented.join(',')} registry=${registered.join(',')}`)
      }
    }
    expect(errors, errors.join('\n')).toEqual([])
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
      const asyncStateEntries = ['AppDataTable', 'AppAsyncRegion', 'AppStateBlock']
      const importedStateEntries = asyncStateEntries.filter((name) => imports.has(name))
      const renderedStateEntries = importedStateEntries.filter((name) => source.includes(`<${name}`))
      expect(
        importedStateEntries.length,
        `${entry.pageKey} 必须导入 AppDataTable、AppAsyncRegion 或 AppStateBlock 承接运行时状态`,
      ).toBeGreaterThan(0)
      expect(
        renderedStateEntries.length,
        `${entry.pageKey} 必须真实渲染已导入的标准运行时状态入口`,
      ).toBeGreaterThan(0)
    }
  })

  it('板块详情异步外壳直接承接既有根布局，不新增第二套 fill 机制', () => {
    const source = sourceForPage('sectors-detail')
    const asyncRegionSource = readFileSync(join(COMPONENTS_DIR, 'AppAsyncRegion.vue'), 'utf-8')

    expect(source).toMatch(/<AppAsyncRegion[\s\S]*?class="sector-detail"[\s\S]*?data-testid="sector-detail-page"/)
    expect(source).not.toContain('<div class="sector-detail"')
    expect(asyncRegionSource).not.toMatch(/\bfill\??\s*:/)
    expect(asyncRegionSource).not.toContain('app-async-region--fill')
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
    expect(getPageLayout('config-tech').slots).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: 'techFilters', component: 'filter-bar', parentId: 'body' }),
    ]))
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
        from '@/components/stock-chart/StockChartWorkspace.vue'
      import { default as DrawerAlias } from '@/components/PageDrawer.vue'
      import LayoutAlias from '@/layout/components/LayoutHost.vue'
      import type { HelpTipProps } from '@/components/HelpTip.vue'
      </script>
    `)
    expect([...components].sort()).toEqual(['LayoutHost', 'PageDrawer', 'StockChartWorkspace'])
  })

  it('DESIGN 组件登记只读取核心真实复用组件表格第一列', () => {
    const components = coreComponentNames(`
核心真实复用组件清单：

| 真实组件 | 路径 |
|---|---|
| \`InsideTable\` / \`InsidePair\` | \`frontend/src/components/InsideTable.vue\`、\`frontend/src/components/InsidePair.vue\` |

### 后续章节

| Composable | 路径 |
|---|---|
| \`OutsideSection\` | x |
    `)
    expect([...components].sort()).toEqual(['InsidePair', 'InsideTable'])
  })

  it('DESIGN 核心真实组件登记必须指向同名运行时组件文件', () => {
    const errors: string[] = []
    for (const row of coreComponentRows(DESIGN_MD)) {
      const runtimePaths = row.names.map((name) => row.paths.find((path) => {
        const extension = extname(path)
        return ['.vue', '.ts'].includes(extension) && basename(path, extension) === name
      }))
      row.names.forEach((name, index) => {
        const path = runtimePaths[index]
        if (!path) {
          errors.push(`${name} 缺少同名运行时组件文件`)
          return
        }
        if (!/^frontend\/src\/(components|layout\/components)\/.+\.(vue|ts)$/.test(path)) {
          errors.push(`${name} 路径不属于真实复用组件目录: ${path}`)
          return
        }
        if (!existsSync(new URL(`../../../../${path}`, import.meta.url))) errors.push(`${name} 文件不存在: ${path}`)
      })
      for (const path of row.paths.filter((candidate) => !runtimePaths.includes(candidate))) {
        if (!path.startsWith('frontend/src/') || !existsSync(new URL(`../../../../${path}`, import.meta.url))) {
          errors.push(`${row.names.join('/')} 的辅助路径不存在: ${path}`)
        }
      }
    }
    expect(errors, errors.join('\n')).toEqual([])
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
      expect(
        source,
        `${entry.pageKey} 必须把后端组件字段允许层级传给页面设置抽屉，避免分层策略只在配置中心生效`,
      ).toContain('componentAllowedLayers')
    }
  })

  it('具有稳定真实实现的逻辑组件必须由页面实际消费对应组件', () => {
    for (const entry of PAGE_REGISTRY) {
      const source = sourceTreeForPage(entry.pageKey)
      const imports = runtimeComponentImports(source)
      const kinds = new Set(entry.layout.slots.map((slot) => slot.component))
      for (const kind of kinds) {
        for (const component of SLOT_RUNTIME_COMPONENTS[kind] ?? []) {
          expect(
            imports.has(component),
            `${entry.pageKey} 声明 ${kind}，但页面组件树未导入真实组件 ${component}`,
          ).toBe(true)
          expect(
            source.includes(`<${component}`),
            `${entry.pageKey} 声明 ${kind}，但页面组件树未真实渲染 <${component}>`,
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
    expect(tableUsers).toEqual(expect.arrayContaining(['data-quality']))
    const wideTableUsers = listComponentUsage('wide-table').map((u) => u.pageKey)
    expect(wideTableUsers).toEqual(expect.arrayContaining(['board', 'screen', 'stocks']))
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

  it('所有 slot 都按组件种类自动推导字段，不存在页面字段白名单', () => {
    for (const entry of PAGE_REGISTRY) {
      expect('consumedComponentFields' in entry, `${entry.pageKey} 不得保留逐页面字段白名单`).toBe(false)
      for (const slot of entry.layout.slots) {
        for (const field of applicableComponentFields(entry, slot.id)) {
          expect(getComponentFieldDef(slot.component, field.key)).toBe(field)
        }
      }
    }
  })

  it('可配置列必须由页面真实消费显隐状态，禁止设置候选与表格渲染漂移', () => {
    for (const entry of PAGE_REGISTRY) {
      const configurableSlots = Object.entries(entry.componentMeta ?? {}).filter(([, meta]) =>
        Boolean(meta.columns?.length))
      if (!configurableSlots.length) continue

      const source = sourceTreeForPage(entry.pageKey)
      const pageSource = sourceForPage(entry.pageKey)
      const visibleKeys = configurableColumnVisibilityKeys(source)
      for (const [slotId, meta] of configurableSlots) {
        for (const column of meta.columns ?? []) {
          const sharedRankedResultConsumption = pageSource.includes('useRankedStockResultView')
            && new RegExp(`['"]${escapeRegExp(column.key)}['"]`).test(pageSource)
          expect(
            visibleKeys.has(column.key) || sharedRankedResultConsumption,
            `${entry.pageKey}.${slotId}.${column.key} 已登记为可配置列，但页面没有真实显隐判断`,
          ).toBe(true)
        }
      }
    }
  })

  it('T8 只为四个既有业务表消费行业走势与概念走势列', () => {
    const actual = new Set<string>()
    for (const entry of PAGE_REGISTRY) {
      for (const [slotId, meta] of Object.entries(entry.componentMeta ?? {})) {
        for (const column of meta.columns ?? []) {
          if (column.key === 'relatedIndustry' || column.key === 'relatedConcept') {
            actual.add(`${entry.pageKey}.${slotId}.${column.key}`)
            expect(column.label).toBe(column.key === 'relatedIndustry' ? '行业走势' : '概念走势')
          }
        }
      }
    }
    expect(actual).toEqual(RELATED_BOARD_COLUMNS)

    const consumers = [
      { pageKey: 'board', visible: 'colVisible' },
      { pageKey: 'screen', visible: 'colVisible' },
      { pageKey: 'stocks', visible: 'colVisible' },
      { pageKey: 'stocks', visible: 'groupColVisible' },
    ]
    for (const consumer of consumers) {
      const source = sourceTreeForPage(consumer.pageKey)
      const pageSource = sourceForPage(consumer.pageKey)
      expect(source).toContain("import RelatedBoardCell from '@/components/RelatedBoardCell.vue'")
      for (const [key, type] of [['relatedIndustry', 'industry'], ['relatedConcept', 'concept']]) {
        expect(
          source.includes(`${consumer.visible}('${key}')`)
          || (pageSource.includes('useRankedStockResultView') && pageSource.includes(`'${key}'`)),
        ).toBe(true)
        expect(source).toMatch(new RegExp(`<RelatedBoardCell[^>]+board-type=["']${type}["']`))
      }
      expect(source).toContain(':return-path="route.fullPath"')
    }
  })

  it('固定高度股票图表统一经外层容器消费 chart.minHeight，自适应工作台不机械套用', () => {
    const stockDetail = getPageEntry('stock-detail')!
    const sectorDetail = getPageEntry('sectors-detail')!
    const training = getPageEntry('training')!
    const sectorWorkbench = getPageEntry('sectors')!

    expect(applicableComponentFields(stockDetail, 'chart').map((field) => field.key)).not.toContain('minHeight')
    expect(stockDetail.layout.slots.find((slot) => slot.id === 'chart')).toMatchObject({
      component: 'chart',
      parentId: 'workspace',
    })
    expect(sourceForPage('stock-detail')).not.toContain("componentValueOf('chart', 'minHeight')")
    expect(sourceForPage('stock-detail')).not.toContain('<StockChartRegion')

    expect(applicableComponentFields(sectorDetail, 'chart').map((field) => field.key)).not.toContain('minHeight')
    expect(sectorDetail.layout.slots.find((slot) => slot.id === 'chart')).toMatchObject({
      component: 'chart',
      parentId: 'workspace',
    })
    expect(sourceForPage('sectors-detail')).not.toContain("componentValueOf('chart', 'minHeight')")
    expect(sourceForPage('sectors-detail')).not.toContain('<StockChartRegion')
    expect(sourceForPage('sectors-detail')).toContain('fit-available-height')

    expect(applicableComponentFields(training, 'chart').map((field) => field.key)).toContain('minHeight')
    expect(training.layout.slots.find((slot) => slot.id === 'chart')).toMatchObject({
      component: 'chart',
      config: { minHeight: 650 },
    })

    const trainingSource = sourceForPage('training')
    expect(trainingSource).toContain("import StockChartRegion from '@/components/stock-chart/StockChartRegion.vue'")
    expect(trainingSource).toContain('<StockChartRegion')
    expect(trainingSource).toContain(':total-height="configuredChartHeight"')
    expect(trainingSource).toContain(':min-height="contentHeight"')
    expect(trainingSource).not.toMatch(/configuredChartHeight(?:\.value)?\s*-/)

    expect(sectorWorkbench.layout.slots.find((slot) => slot.id === 'chart')?.component).toBe('chart')
    expect(applicableComponentFields(sectorWorkbench, 'chart').map((field) => field.key)).not.toContain('minHeight')
  })

  it('个股详情完整模块显隐归布局，分区内部字段归组件设置', () => {
    const entry = getPageEntry('stock-detail')!
    expect(entry.layout.editable.map((knob) => knob.path)).toEqual(expect.arrayContaining([
      'slots.collectionNavigation.visible',
      'slots.relatedBoards.visible',
      'slots.indicatorSnapshot.visible',
      'slots.tradeEvaluation.visible',
    ]))
    expect(entry.layout.editable.filter((knob) => knob.path.endsWith('.visible'))
      .every((knob) => knob.group === '模块显示')).toBe(true)
    expect(applicableComponentFields(entry, 'indicatorSnapshot').map((field) => field.key))
      .toEqual(['visibleIndicatorFields'])
    expect(sourceForPage('stock-detail')).not.toContain("componentValueOf('indicatorSnapshot', 'visible')")
    expect(sourceForPage('stock-detail')).toContain("valueOf('slots.indicatorSnapshot.visible')")
  })

  it('页面展示能力归组件设置，业务选项不再保留平行字段或空分组', () => {
    const overview = getPageEntry('data-overview')!
    const ingest = getPageEntry('data-ingest')!
    expect(applicableComponentFields(overview, 'summary').map((field) => field.key))
      .toContain('visibleItems')
    expect(applicableComponentFields(ingest, 'taskLogDrawer').map((field) => field.key))
      .toContain('autoScroll')

    const overviewSource = sourceForPage('data-overview')
    const ingestSource = sourceForPage('data-ingest')
    const sectorDetailSource = sourceForPage('sectors-detail')
    expect(overviewSource).not.toContain('settings.kpi')
    expect(overviewSource).toContain("componentValueOf('summary', 'visibleItems')")
    expect(ingestSource).not.toContain('settings.autoScroll')
    expect(ingestSource).toContain("componentValueOf('taskLogDrawer', 'autoScroll')")
    expect(sectorDetailSource).not.toContain('<template #business>')
  })

  it('分时归档登记为既有概览指标选项，默认可见并复用 visibleItems 配置', () => {
    const page = getPageEntry('data-overview')!
    expect(page.componentMeta?.summary?.items).toContainEqual({ key: 'intraday', label: '分时归档' })
    expect(getPageLayout('data-overview').slots.find((slot) => slot.id === 'summary')?.config?.visibleItems)
      .toContain('intraday')
    expect(applicableComponentFields(page, 'summary').map((field) => field.key)).toEqual(['visibleItems'])
    expect(getPageLayout('data-overview').slots.find((slot) => slot.id === 'workspace')?.minH).toBe(300)
  })

  it('业务选项插槽不得登记空内容', () => {
    const offenders: string[] = []
    for (const entry of PAGE_REGISTRY) {
      const source = sourceForPage(entry.pageKey)
      if (!source) continue
      for (const match of source.matchAll(/<template\s+(?:v-if="[^"]*"\s+)?#business\b[^>]*>([\s\S]*?)<\/template>/g)) {
        if (!match[1]?.replace(/<!--[\s\S]*?-->/g, '').trim()) offenders.push(entry.pageKey)
      }
    }
    expect(offenders, `以下页面登记了空业务选项分组：\n${offenders.join('\n')}`).toEqual([])
  })

  it('行情主从工作台统一在组件设置消费默认比例，主区拖动不反写配置层', () => {
    for (const pageKey of [
      'stocks',
      'board',
      'limit-ladder',
      'screen',
      'stock-detail',
      'sectors',
      'sectors-detail',
    ]) {
      expect(getPageEntry(pageKey)?.layout.slots.find((slot) => slot.id === 'workspace')?.minH)
        .toBe(MARKET_WORKSPACE_MIN_HEIGHT)
    }

    for (const pageKey of ['stocks', 'board', 'limit-ladder', 'sectors']) {
      const entry = getPageEntry(pageKey)!
      expect(applicableComponentFields(entry, 'workspace').map((field) => field.key)).toContain('masterRatio')
      expect(applicableComponentFields(entry, 'workspace').map((field) => field.key)).toContain('masterRatioProfiles')
      const source = sourceForPage(pageKey)
      expect(source).toContain('<MarketMasterDetailWorkspace')
      expect(source).toContain("componentValueOf('workspace', 'masterRatio')")
      expect(source).toContain("componentValueOf('workspace', 'masterRatioProfiles')")
      expect(source).not.toContain('business-component-slot-ids')
      expect(source).toContain(':component-runtime-value-of="componentRuntimeValueOf"')
      expect(source).not.toContain('@master-ratio-change="setCurrentMasterRatio"')
      expect(source).toContain('@master-ratio-sample-change="setCurrentMasterRatioSample"')
    }

    for (const pageKey of ['stock-detail', 'sectors-detail']) {
      const detailSource = sourceForPage(pageKey)
      expect(applicableComponentFields(getPageEntry(pageKey)!, 'workspace').map((field) => field.key))
        .toEqual(expect.arrayContaining(['masterRatio', 'masterRatioProfiles']))
      expect(detailSource).toContain('<AppSplitWorkspace')
      expect(detailSource).toContain("componentValueOf('workspace', 'masterRatio')")
      expect(detailSource).toContain("componentValueOf('workspace', 'masterRatioProfiles')")
      expect(detailSource).toContain(':component-runtime-value-of="componentRuntimeValueOf"')
      expect(detailSource).not.toContain('@primary-ratio-change="setCurrentMasterRatio"')
      expect(detailSource).toContain('@primary-ratio-sample-change="setCurrentMasterRatioSample"')
    }

    const workspaceSource = readFileSync(
      new URL('../../components/AppSplitWorkspace.vue', import.meta.url),
      'utf8',
    )
    expect(workspaceSource).toContain('useDefaultedSessionValue(configuredPrimaryWidth, {')
    expect(workspaceSource).not.toContain('setComponentKnob')
    const rankedWorkbenchSource = readFileSync(
      new URL('../../components/ranked-stock/RankedStockWorkbench.vue', import.meta.url),
      'utf8',
    )
    expect(rankedWorkbenchSource).toContain("heightMode: 'adaptive'")
    expect(sourceForPage('config-score'))
      .toMatch(/<AppDataTable[^>]*embedded[^>]*>/)
    expect(sourceForPage('data-schedule'))
      .toContain(':max-height="LEADING_WORKBENCH_TABLE_MAX_HEIGHT"')
    expect(sourceForPage('data-schedule'))
      .toMatch(/<AppDataTable[\s\S]*?:data="jobs"[\s\S]*?embedded[\s\S]*?>/)
    expect(sourceForPage('data-schedule'))
      .toContain(':pagination="{ currentPage: jobPage, pageSize: jobPageSize, total: jobTotal, pageSizes: PAGE_SIZE_OPTIONS }"')
    expect(sourceForPage('data-schedule'))
      .toMatch(/listSchedules\(\{[\s\S]*page: jobPage\.value,[\s\S]*size: jobPageSize\.value,[\s\S]*sort_by: sortBy\.value,[\s\S]*sort_order: sortOrder\.value/)
    expect(getPageEntry('data-schedule')!.layout.slots.find((slot) => slot.id === 'jobTable'))
      .toMatchObject({ minH: 300, idealH: 960, config: { pagination: true, pageSize: 20 } })
    expect(getPageEntry('data-schedule')!.layout.slots.find((slot) => slot.id === 'sourcePanel'))
      .toMatchObject({ component: 'section', growMain: true, minH: 200 })
    expect(getPageEntry('data-ingest')!.layout.slots.find((slot) => slot.id === 'workspace'))
      .toMatchObject({ component: 'tabs', growMain: true, minH: 520 })
    expect(sourceForPage('data-ingest')).not.toContain('min-height: 520px')
    expect(sourceForPage('config-score')).not.toContain('height-mode=')
    expect(sourceForPage('screen')).not.toContain('height-mode=')
  })

  it('板块列表恢复业务偏好和组件配置，详情仅恢复自身组件配置', () => {
    const listSource = sourceForPage('sectors')
    const detailSource = sourceForPage('sectors-detail')

    expect(listSource).toContain('@reset="resetSettings"')
    expect(listSource).toMatch(/function resetSettings\(\)[\s\S]*reset\(\)[\s\S]*resetLayout\(\)/)
    expect(detailSource).toContain('@reset="resetSettings"')
    expect(detailSource).toMatch(/function resetSettings\(\)[\s\S]*resetLayout\(\)/)
    expect(detailSource).not.toContain('usePageSettings(')
  })

  it('data-table / wide-table 必须消费并真实接入 border 页面级配置', () => {
    for (const entry of PAGE_REGISTRY) {
      const tableSlots = entry.layout.slots.filter((slot) => slot.component === 'data-table' || slot.component === 'wide-table')
      if (!tableSlots.length) continue
      const source = sourceForPage(entry.pageKey)
      expect(source, `${entry.pageKey} 使用表格组件但无法从 router 定位 Vue 页面源码`).not.toBe('')
      for (const slot of tableSlots) {
        expect(applicableComponentFields(entry, slot.id).map((field) => field.key)).toContain('border')
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

  it('复合业务组件从真实消费点反查槽位、运行时配置和业务偏好闭环', () => {
    const registeredSources = new Set(COMPOSITE_COMPONENT_CONTRACTS.map((contract) => contract.sourcePath))
    for (const file of vueFiles(COMPONENTS_DIR)) {
      const source = readFileSync(file, 'utf8')
      if (!source.includes('registryPageKey: string')) continue
      const relativeSource = `components/${file.slice(COMPONENTS_DIR.length).replace(/^\//, '')}`
      expect(
        registeredSources.has(relativeSource),
        `${relativeSource} 声明了 registryPageKey，但未进入 COMPOSITE_COMPONENT_CONTRACTS`,
      ).toBe(true)
    }

    for (const contract of COMPOSITE_COMPONENT_CONTRACTS) {
      const componentSource = readFileSync(new URL(`../../${contract.sourcePath}`, import.meta.url), 'utf8')
      expect(componentSource).toContain('registryPageKey: string')
      for (const forbidden of contract.forbiddenComponentSources) {
        expect(componentSource, `${contract.componentName} 不得写死业务口径 ${forbidden}`).not.toContain(forbidden)
      }

      const consumers: { file: string; pageKey: string; tag: string }[] = []
      for (const file of vueFiles(VIEWS_DIR)) {
        const source = readFileSync(file, 'utf8')
        const tags = [...source.matchAll(new RegExp(`<${contract.componentName}\\b[\\s\\S]*?\\/>`, 'g'))]
          .map((match) => match[0])
        for (const tag of tags) {
          const pageKey = new RegExp(`${contract.pageKeyAttribute}=["']([^"']+)["']`).exec(tag)?.[1]
          expect(pageKey, `${basename(file)} 的 ${contract.componentName} 必须声明 ${contract.pageKeyAttribute}`).toBeTruthy()
          if (pageKey) consumers.push({ file, pageKey, tag })
        }
      }

      expect(consumers.length, `${contract.componentName} 契约没有真实消费点`).toBeGreaterThan(0)
      for (const { file, pageKey, tag } of consumers) {
        const source = readFileSync(file, 'utf8')
        const entry = getPageEntry(pageKey)
        expect(entry, `${basename(file)} 引用的 pageKey=${pageKey} 未登记`).toBeTruthy()
        expect(entry?.supportsComponentConfig, `${pageKey} 必须开放组件设置`).toBe(true)

        for (const slotContract of contract.slots) {
          expect(entry?.layout.slots).toContainEqual(expect.objectContaining({
            id: slotContract.id,
            component: slotContract.kind,
            ...(slotContract.parentId ? { parentId: slotContract.parentId } : {}),
          }))
          expect(applicableComponentFields(entry!, slotContract.id).map((field) => field.key))
            .toEqual(expect.arrayContaining(slotContract.requiredFields))
        }
        for (const fragment of contract.consumerRuntimeSources) {
          expect(source, `${pageKey} 缺少复合组件运行时配置消费：${fragment}`).toContain(fragment)
        }
      }
    }
  })

  it('业务偏好从所有运行时消费点反查默认值、抽屉入口与 prop 传递', () => {
    const registeredCompositeSources = new Set(
      COMPOSITE_COMPONENT_CONTRACTS.map((contract) => contract.sourcePath),
    )

    for (const preference of PAGE_BUSINESS_PREFERENCE_CONTRACTS) {
      const consumerPattern = preference.consumerComponents.map(escapeRegExp).join('|')
      const tagPattern = new RegExp(`<(${consumerPattern})\\b([^>]*)>`, 'g')

      // 中间组件如果承接业务偏好，必须作为复合组件登记并以必填 prop 原样透传。
      for (const file of vueFiles(COMPONENTS_DIR)) {
        const source = readFileSync(file, 'utf8')
        const tags = [...source.matchAll(tagPattern)]
        if (!tags.length) continue
        const relativeSource = `components/${file.slice(COMPONENTS_DIR.length).replace(/^\//, '')}`
        expect(source, `${relativeSource} 承接 ${preference.label} 时必须声明 registryPageKey`)
          .toContain('registryPageKey: string')
        expect(
          registeredCompositeSources.has(relativeSource),
          `${relativeSource} 承接 ${preference.label} 但未登记复合组件契约`,
        ).toBe(true)
        expect(source, `${relativeSource} 的 ${preference.key} 必须是必填 prop`)
          .toMatch(new RegExp(`\\b${escapeRegExp(preference.key)}\\s*:`))
        expect(source, `${relativeSource} 不得把 ${preference.label} 声明为可选 prop`)
          .not.toMatch(new RegExp(`\\b${escapeRegExp(preference.key)}\\s*\\?:`))
        for (const tag of tags) {
          expect(tag[0], `${relativeSource} 必须原样透传 ${preference.key}`)
            .toContain(`:${preference.prop}="${preference.key}"`)
        }
      }

      // 页面直接消费或消费已登记复合组件时，必须具备长期默认、抽屉入口和动态传参。
      for (const entry of PAGE_REGISTRY) {
        const source = sourceForPage(entry.pageKey)
        if (!source) continue
        const tags = [...source.matchAll(tagPattern)].filter((match) => {
          const explicitPageKey = /registry-page-key=["']([^"']+)["']/.exec(match[0])?.[1]
          return !explicitPageKey || explicitPageKey === entry.pageKey
        })
        if (!tags.length) continue

        expect(source, `${entry.pageKey} 使用 ${preference.label} 但未声明默认值`)
          .toContain(preference.defaultValueSource)
        expect(source, `${entry.pageKey} 使用 ${preference.label} 但设置抽屉缺少写入入口`)
          .toContain(`label="${preference.label}"`)
        for (const tag of tags) {
          expect(tag[0], `${entry.pageKey} 未把 ${preference.key} 动态传给 ${tag[1]}`)
            .toContain(`:${preference.prop}="${preference.key}"`)
          for (const literal of preference.forbiddenLiteralValues) {
            expect(tag[0], `${entry.pageKey} 不得把 ${preference.label} 写死为 '${literal}'`)
              .not.toContain(`${preference.prop}="${literal}"`)
          }
        }
      }
    }
  })

  it('可交互排序字段必须进入 defaultSort 配置闭环', () => {
    for (const entry of PAGE_REGISTRY) {
      for (const [slotId, meta] of Object.entries(entry.componentMeta ?? {})) {
        if (!meta.sortFields?.length) continue

        expect(applicableComponentFields(entry, slotId).map((field) => field.key)).toContain('defaultSort')

        const defaultSort = entry.layout.slots.find((slot) => slot.id === slotId)?.config?.defaultSort
        expect(
          defaultSort,
          `${entry.pageKey}.${slotId} 声明 sortFields 后必须在 slot.config 声明安全默认排序`,
        ).toBeDefined()
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

  it('声明 sortFields 的页面源码必须接入列头排序（会话态，不回写 defaultSort）', () => {
    for (const entry of PAGE_REGISTRY) {
      const sortableSlots = Object.entries(entry.componentMeta ?? {}).filter(([, meta]) => meta.sortFields?.length)
      if (!sortableSlots.length) continue

      const source = sourceForPage(entry.pageKey)
      expect(source, `${entry.pageKey} 声明 sortFields 但无法从 router 定位 Vue 页面源码`).not.toBe('')
      expect(source, `${entry.pageKey} 声明 sortFields 后页面必须接入 @sort-change`).toContain('@sort-change')

      for (const [slotId, meta] of sortableSlots) {
        // 单向默认机制：页面用 componentValueOf 读默认排序初始化会话态，列头排序只进会话、不回写 defaultSort。
        const readsDefaultSort =
          source.includes(`componentValueOf('${slotId}', 'defaultSort'`) ||
          source.includes(`componentValueOf("${slotId}", "defaultSort"`) ||
          (source.includes('useTableSort') && source.includes(`slotId: '${slotId}'`)) ||
          (source.includes('useTableSort') && source.includes(`slotId: "${slotId}"`)) ||
          (slotId === 'result' && source.includes('useRankedStockResultView'))
        expect(
          readsDefaultSort,
          `${entry.pageKey}.${slotId} 声明 sortFields 后页面必须消费 slots.${slotId}.config.defaultSort 作为默认排序`,
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

  it('pageSize 单向默认：登记 pageSize 的 slot 必须通过分页会话 composable 消费默认值', () => {
    // DESIGN「设置抽屉」节单向默认机制：组件配置层只提供默认值，页面用 componentValueOf 读默认值
    // 并统一交给 useComponentPageSizeSession 初始化会话态，分页器改动不回写配置层。
    // 用 sourceForPage 精确映射页面，避免按 slotId 全局 grep 误配。
    for (const entry of PAGE_REGISTRY) {
      const pageSizeSlots = entry.layout.slots
        .filter((slot) => applicableComponentFields(entry, slot.id).some((field) => field.key === 'pageSize'))
        .map((slot) => slot.id)
      if (!pageSizeSlots.length) continue

      const source = sourceForPage(entry.pageKey)
      expect(source, `${entry.pageKey} 登记 pageSize 但无法从 router 定位 Vue 页面源码`).not.toBe('')
      expect(
        source.includes('useComponentPageSizeSession('),
        `${entry.pageKey} 登记了 pageSize 但未消费统一分页会话 composable`,
      ).toBe(true)
      for (const slotId of pageSizeSlots) {
        const consumesThroughSession =
          source.includes(`resolveDefault: () => componentValueOf('${slotId}', 'pageSize'`)
          || source.includes(`resolveDefault: () => componentValueOf("${slotId}", "pageSize"`)
        expect(
          consumesThroughSession,
          `${entry.pageKey}.${slotId} 登记了 pageSize 但未通过统一分页会话 composable 消费默认值`,
        ).toBe(true)
      }
    }
  })

  it('单向默认反向拦截：registry 页面不得直接调用 setComponentKnob 写配置层（任何字段，页面改动只进会话态）', () => {
    // DESIGN「设置抽屉」节单向默认机制：组件配置层只提供默认值，页面改动绝不写回。字段无关——
    // 任何字段的写回都违规，不限于 defaultSort/pageSize/defaultActive。合法写入口只有两处：
    // 抽屉渲染器 ComponentAutoSettings（经 drawerConfig 以属性接收，非页面直接调用）和配置中心编辑器
    // （LayoutPagesView 用自有 setPageComponentValue）。页面源码出现 setComponentKnob(<slot>,...) 直调即拦截。
    const violations: string[] = []
    for (const entry of PAGE_REGISTRY) {
      if (!entry.supportsComponentConfig) continue
      const source = sourceForPage(entry.pageKey)
      if (!source) continue
      const writes = directComponentKnobWrites(source, `${entry.pageKey}.vue`)
      if (writes.length) {
        violations.push(`${entry.pageKey} 页面源码直接调用 ${writes.join('/')} 写配置层（违反单向默认机制，字段无关）`)
      }
    }
    expect(violations, `以下页面把页面改动写回组件配置层：\n${violations.join('\n')}`).toEqual([])
  })

  it('业务偏好不静默持久化：usePageSettings defaults 的每个顶层字段必须被页面消费（含 computed/别名）', () => {
    // DESIGN「设置抽屉」节：defaults 里塞字段即持久化到 PG user_preference；若页面从不消费它，
    // 就是「未配置进抽屉却私自持久化」的死项。只查顶层字段（不展开 indicators/filters 等嵌套子 key，
    // 父级被引用即视为消费）；历史 settings 解构别名同样算消费入口。
    for (const entry of PAGE_REGISTRY) {
      const source = sourceForPage(entry.pageKey)
      if (!source || !source.includes('usePageSettings(')) continue
      const { fields, aliases } = pageSettingsFields(source, `${entry.pageKey}.vue`)
      if (!fields.length) continue
      for (const field of fields) {
        const consumed = aliases.some((alias) => new RegExp(`\\b${alias}\\.${field}\\b`).test(source))
        expect(
          consumed,
          `${entry.pageKey} 的 usePageSettings defaults 字段 '${field}' 未被任何地方消费（${aliases.join('/')}），`
          + `属静默持久化死项——要么接进抽屉业务段，要么从 defaults 移除`,
        ).toBe(true)
      }
    }
  })

  it('业务偏好必须在设置抽屉提供写入入口，不得把会话字段混入持久化载荷', () => {
    for (const entry of PAGE_REGISTRY) {
      const source = sourceForPage(entry.pageKey)
      if (!source || !source.includes('usePageSettings(')) continue
      const { fields, aliases } = pageSettingsFields(source, `${entry.pageKey}.vue`)
      if (!fields.length) continue
      const business = [...source.matchAll(
        /<template\s+#business\b[^>]*>([\s\S]*?)<\/PageSettingsDrawer>/g,
      )].map((match) => match[1]).join('\n')
      const computedFields = computedPageSettingsFieldsInBusiness(
        source,
        `${entry.pageKey}.vue`,
        aliases,
        business,
      )
      for (const field of fields) {
        const directModel = aliases.some((alias) => new RegExp(
          `v-model(?:[:.][^=\\s]+)*\\s*=\\s*["'][^"']*\\b${alias}\\.${field}\\b`,
        ).test(business))
        expect(
          directModel || computedFields.has(field),
          `${entry.pageKey} 的持久化字段 '${field}' 没有设置抽屉写入入口；`
          + '会话字段应移出 usePageSettings，长期默认应补全抽屉闭环',
        ).toBe(true)
      }
    }
  })

  it('业务偏好单向：持久化 settings 不得在业务插槽外被 v-model 直接写回', () => {
    const violations: string[] = []
    for (const entry of PAGE_REGISTRY) {
      const source = sourceForPage(entry.pageKey)
      if (!source || !source.includes('usePageSettings(')) continue
      const { fields, aliases } = pageSettingsFields(source, `${entry.pageKey}.vue`)
      if (!fields.length) continue

      // #business 是 PageSettingsDrawer 的最后一个具名插槽；移除到抽屉闭标签的整段，
      // 避免业务段内部嵌套 template 时被非贪婪正则提前截断。
      const outsideBusiness = source.replace(
        /<template\s+#business\b[^>]*>[\s\S]*?<\/PageSettingsDrawer>/g,
        '</PageSettingsDrawer>',
      )
      for (const alias of aliases) {
        for (const field of fields) {
          const directModel = new RegExp(`v-model(?:[:.][^=\\s]+)*\\s*=\\s*["'][^"']*\\b${alias}\\.${field}\\b`)
          if (directModel.test(outsideBusiness)) {
            violations.push(`${entry.pageKey}: 主区 v-model 直接绑定 ${alias}.${field}`)
          }
        }
      }
    }
    expect(
      violations,
      `页面交互不得把会话改动写回长期默认；请改用独立会话 ref：\n${violations.join('\n')}`,
    ).toEqual([])
  })

  it('页面默认值投影统一使用 useDefaultedSessionValue，不保留 ref + watcher 私有实现', () => {
    const violations: string[] = []
    for (const entry of PAGE_REGISTRY) {
      const source = sourceForPage(entry.pageKey)
      if (!source) continue
      const { aliases } = pageSettingsFields(source, `${entry.pageKey}.vue`)
      const settingsAliasesPattern = aliases.map((alias) => escapeRegExp(alias)).join('|') || 'settings'
      const directSettingsRef = new RegExp(
        `\\bref(?:<[^>]+>)?\\(\\s*(?:Boolean|Number|String)?\\(?\\s*(?:${settingsAliasesPattern})\\.`,
      )
      const directKnownDefaultRef = /\bref(?:<[^>]+>)?\(\s*(?:klineDefault|defaultKlineRange|workspaceTabDefault|sysTabDefault)\.value\s*\)/
      const directSettingsWatcher = new RegExp(
        `watch\\(\\s*\\(\\)\\s*=>\\s*(?:${settingsAliasesPattern})\\.[^,]+,`
        + '\\s*\\([^)]*\\)\\s*=>\\s*\\{?\\s*[\\w.]+\\.value\\s*=',
      )
      if (directSettingsRef.test(source)) violations.push(`${entry.pageKey}: ref(settings.*)`)
      if (directKnownDefaultRef.test(source)) violations.push(`${entry.pageKey}: ref(default.value)`)
      if (directSettingsWatcher.test(source)) violations.push(`${entry.pageKey}: settings watcher 手工回填会话 ref`)
    }
    expect(
      violations,
      `默认值到主区会话态必须复用 useDefaultedSessionValue：\n${violations.join('\n')}`,
    ).toEqual([])
  })

  it('页面业务设置对象统一命名为 settings，不使用页面私有别名', () => {
    const violations: string[] = []
    for (const entry of PAGE_REGISTRY) {
      const source = sourceForPage(entry.pageKey)
      if (!source || !source.includes('usePageSettings(')) continue
      const { aliases } = pageSettingsFields(source, `${entry.pageKey}.vue`)
      for (const alias of aliases) {
        if (alias !== 'settings') violations.push(`${entry.pageKey}: settings 被命名为 ${alias}`)
      }
    }
    expect(
      violations,
      `usePageSettings 返回的业务设置对象统一使用 settings：\n${violations.join('\n')}`,
    ).toEqual([])
  })

  it('连板天梯业务默认必须即时投影到会话态，且普通页面状态不得回写 URL', () => {
    const source = sourceForPage('limit-ladder')
    expect(source).toContain('const filterWindow = useDefaultedSessionValue(')
    expect(source).toContain('const filterBoards = useDefaultedSessionValue(')
    expect(source).toContain('const filterIgnoreSt = useDefaultedSessionValue(')
    expect(source).toContain('const cardSort = useDefaultedSessionValue(')
    expect(source).toContain('const cardSortOrder = useDefaultedSessionValue(')
    expect(source).toContain('onSynced: scheduleDefaultFilterReload')
    expect(source).not.toMatch(/card_sort\s*:/)
    expect(source).not.toMatch(/card_order\s*:/)
    expect(source).not.toContain('filtersToRouteQuery(')
  })

  it('板块行情返回现场必须走当前 Tab 会话，普通筛选、排序和日期不得回写 URL', () => {
    const listSource = sourceForPage('sectors')
    const detailSource = sourceForPage('sectors-detail')
    expect(listSource).toContain('useSectorsSessionStore()')
    expect(listSource).toContain('saveListReturnState({')
    expect(listSource).not.toContain('syncSourceQuery')
    expect(listSource).not.toContain('sourceQuery()')
    expect(listSource).not.toContain('resolveSectorListState(')
    expect(detailSource).toContain('saveDetailReturnState({')
    expect(detailSource).not.toContain('sanitizeSectorSourceQuery(')
    expect(detailSource).not.toContain('router.replace({ path: route.path, query:')
  })

  it('页面不得直接读写浏览器存储，会话与偏好必须经过共享生命周期入口', () => {
    const violations: string[] = []
    for (const entry of PAGE_REGISTRY) {
      const source = sourceForPage(entry.pageKey)
      if (!source) continue
      if (/\b(?:localStorage|sessionStorage)\s*\./.test(source)) violations.push(entry.pageKey)
    }
    expect(
      violations,
      `页面不得私有化浏览器存储，请使用 usePageSettings、pageSessionStorage 或专用共享 composable：\n${violations.join('\n')}`,
    ).toEqual([])
  })

  it('页面不得直接创建私有持久化通道，长期偏好必须进入可审查的页面设置或专用共享契约', () => {
    const violations: string[] = []
    for (const entry of PAGE_REGISTRY) {
      const source = sourceForPage(entry.pageKey)
      if (!source) continue
      if (/\buseUserPreference\s*\(/.test(source)) {
        violations.push(`${entry.pageKey}: 页面直接调用 useUserPreference，可能绕过抽屉登记与单向默认契约`)
      }
    }
    expect(
      violations,
      `页面不得私建静默持久化；全局偏好应封装为共享 composable，页面默认应走 usePageSettings + 抽屉：\n${violations.join('\n')}`,
    ).toEqual([])
  })

  it('多图工作区统一消费 page+slot 组件配置，不再在页面业务偏好维护平行字段', () => {
    for (const entry of PAGE_REGISTRY) {
      const source = sourceForPage(entry.pageKey)
      const stockChartSlot = entry.layout.slots.find((slot) => slot.config?.stockChart)
      if (!stockChartSlot) continue
      expect(source).toContain('useStockChartComponentConfig({')
      expect(source).toContain(':height-ratios="chartPreferences.currentRatios.value"')
      if (!['screen', 'config-score'].includes(entry.pageKey)) {
        expect(source).toContain('useLegacyStockChartPreferenceMigration({')
      }
      expect(source).not.toContain('<StockChartSettingSection')
      expect(source).not.toMatch(/\bcharts:\s*createDefaultStockChartPreferences\(/)
    }
  })

  it('常规行情图表统一登记并消费 K 线周期与测算默认值', () => {
    const enabledPages = PAGE_REGISTRY
      .filter((entry) => entry.layout.slots.some((slot) => slot.config?.returnMeasurement === true))
      .map((entry) => entry.pageKey)
      .sort()
    expect(enabledPages).toEqual([
      'board',
      'config-score',
      'limit-ladder',
      'screen',
      'sectors',
      'sectors-detail',
      'stock-detail',
      'stocks',
    ])
    for (const pageKey of enabledPages) {
      const entry = PAGE_REGISTRY.find((candidate) => candidate.pageKey === pageKey)!
      const chart = entry.layout.slots.find((slot) => slot.config?.returnMeasurement === true)!
      const fields = applicableComponentFields(entry, chart.id).map((field) => field.key)
      expect(fields, pageKey).toContain('klinePeriod')
      expect(fields, pageKey).toContain('returnMeasurementMode')
      const source = sourceForPage(pageKey)
      expect(source, pageKey).toContain(
        'v-model:return-measurement-mode="chartPreferences.returnMeasurementMode.value"',
      )
      expect(source, pageKey).toContain(
        'v-model:kline-period="chartPreferences.klinePeriod.value"',
      )
    }
    for (const pageKey of ['backtest', 'training']) {
      const entry = PAGE_REGISTRY.find((candidate) => candidate.pageKey === pageKey)!
      const chart = entry.layout.slots.find((slot) => slot.component === 'chart')!
      const fields = applicableComponentFields(entry, chart.id).map((field) => field.key)
      expect(fields, pageKey).not.toContain('klinePeriod')
      expect(fields, pageKey).not.toContain('returnMeasurementMode')
    }
  })

  it('联动走势默认项按股票与板块组件模型分别登记并消费', () => {
    for (const pageKey of ['board', 'stocks', 'limit-ladder', 'screen', 'config-score']) {
      const entry = PAGE_REGISTRY.find((candidate) => candidate.pageKey === pageKey)!
      const chart = entry.layout.slots.find((slot) => slot.config?.stockAnalysis)!
      expect(chart, pageKey).toBeDefined()
      expect(applicableComponentFields(entry, chart.id).map((field) => field.key))
        .toContain('stockAnalysis')
      const source = sourceForPage(pageKey)
      expect(source, pageKey).toContain('chartPreferences.stockAnalysis')
    }

    const sectors = PAGE_REGISTRY.find((candidate) => candidate.pageKey === 'sectors')!
    const sectorChart = sectors.layout.slots.find((slot) => slot.config?.sectorAnalysis)!
    expect(sectorChart).toBeDefined()
    expect(applicableComponentFields(sectors, sectorChart.id).map((field) => field.key))
      .toContain('sectorAnalysis')
    expect(sourceForPage('sectors')).toContain('chartPreferences.sectorAnalysis.value')
  })

  it('个股与板块详情始终开放图表组件实例设置', () => {
    for (const pageKey of ['stock-detail', 'sectors-detail']) {
      const source = sourceForPage(pageKey)
      expect(source).toContain(':business-visible="true"')
      expect(source).toMatch(/:component-runtime-value-of="(?:chartPreferences\.componentRuntimeValueOf|componentRuntimeValueOf)"/)
      expect(source).toContain('useStockChartComponentConfig({')
      expect(source).not.toContain('<StockChartSettingSection')
    }
  })

  it('回测交易回放消费统一多图工作区和共享默认比例，不再保留旧画布分叉', () => {
    const source = sourceForPage('backtest')
    expect(source).toContain("import StockChartWorkspace from '@/components/stock-chart/StockChartWorkspace.vue'")
    expect(source).toContain('<StockChartWorkspace')
    expect(source).toContain('useStockChartComponentConfig({')
    expect(source).toContain(':height-ratios="chartPreferences.currentRatios.value"')
    expect(source).not.toContain('CandleChart')
  })

  it('股票分析工作台统一消费默认会话投影与共享选择状态机', () => {
    for (const pageKey of ['board', 'stocks']) {
      const source = sourceForPage(pageKey)
      expect(
        source.includes('useStockAnalysisSession('),
        `${pageKey} 必须通过 useStockAnalysisSession 消费抽屉和 K 线默认值`,
      ).toBe(true)
      expect(
        source.includes('useStockAnalysisSelection('),
        `${pageKey} 必须通过 useStockAnalysisSelection 维护当前观察和对比队列`,
      ).toBe(true)
      expect(source).not.toContain('analysisLookup = ref')
      expect(source).not.toContain('pinnedAnalysisCodes = ref')
    }

    const stocksSource = sourceForPage('stocks')
    expect(
      stocksSource.includes('activeAnalysisItem.value?.last_date'),
      'stocks 分组行情截止日必须取当前观察股票，而不是当前页第一行',
    ).toBe(true)
    expect(stocksSource).not.toContain('groupRows.value[0]?.last_date')
  })
})
