/**
 * 页面注册表完整性（P0/P1）——保证 pageRegistry 作为单一事实源始终自洽：
 * 每个登记布局都过校验器、pageKey 自洽、无重复、editable 路径合法、getPageLayout 返回深拷贝。
 */
import { describe, expect, it } from 'vitest'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
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

/** 收集页面真实用于列显隐判断的 key，避免 componentMeta 只生成设置项却没有业务渲染消费。 */
function configurableColumnVisibilityKeys(source: string): Set<string> {
  const keys = new Set<string>()
  for (const match of source.matchAll(/\b[A-Za-z_$][\w$]*Visible\(\s*['"]([^'"]+)['"]\s*\)/g)) {
    keys.add(match[1]!)
  }
  return keys
}

/** 对象字面量的顶层属性名（不展开嵌套对象/数组的子 key）。 */
function topLevelKeys(object: ts.ObjectLiteralExpression): string[] {
  return object.properties
    .filter((p): p is ts.PropertyAssignment => ts.isPropertyAssignment(p))
    .map((p) => (ts.isIdentifier(p.name) || ts.isStringLiteral(p.name) ? p.name.text : ''))
    .filter(Boolean)
}

/**
 * 解析页面 usePageSettings 的业务偏好 defaults 顶层字段 + settings 别名。
 * defaults 可能是内联对象字面量或 const 引用；别名来自 `const { settings: cfg } = ...` 解构。
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
      // 解构别名：const { settings: cfg } = usePageSettings(...)
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
| \`InsideTable\` / \`InsidePair\` | \`frontend/src/components/InsideTable.vue\`、\`frontend/src/components/InsidePair.vue\` |

### 后续章节

| Composable | 路径 |
|---|---|
| \`OutsideSection\` | x |
    `)
    expect([...components].sort()).toEqual(['InsidePair', 'InsideTable'])
  })

  it('DESIGN 核心真实组件登记必须指向同名运行时 Vue 文件', () => {
    const errors: string[] = []
    for (const row of coreComponentRows(DESIGN_MD)) {
      const vuePaths = row.paths.filter((path) => path.endsWith('.vue'))
      if (row.names.length !== vuePaths.length) {
        errors.push(`${row.names.join('/')} 的组件名与路径数量不一致`)
        continue
      }
      row.names.forEach((name, index) => {
        const path = vuePaths[index]!
        if (!/^frontend\/src\/(components|layout\/components)\/.+\.vue$/.test(path)) {
          errors.push(`${name} 路径不属于真实复用组件目录: ${path}`)
          return
        }
        if (basename(path, '.vue') !== name) errors.push(`${name} 与文件名不一致: ${path}`)
        if (!existsSync(new URL(`../../../../${path}`, import.meta.url))) errors.push(`${name} 文件不存在: ${path}`)
      })
      for (const path of row.paths.filter((candidate) => !candidate.endsWith('.vue'))) {
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
    expect(tableUsers).toEqual(expect.arrayContaining(['screen', 'data-quality']))
    const wideTableUsers = listComponentUsage('wide-table').map((u) => u.pageKey)
    expect(wideTableUsers).toEqual(expect.arrayContaining(['board', 'stocks']))
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

  it('可配置列必须由页面真实消费显隐状态，禁止设置候选与表格渲染漂移', () => {
    for (const entry of PAGE_REGISTRY) {
      const configurableSlots = Object.entries(entry.componentMeta ?? {}).filter(([slotId, meta]) =>
        Boolean(meta.columns?.length)
        && (entry.consumedComponentFields?.[slotId] ?? []).includes('hiddenColumns'))
      if (!configurableSlots.length) continue

      const source = sourceForPage(entry.pageKey)
      const visibleKeys = configurableColumnVisibilityKeys(source)
      for (const [slotId, meta] of configurableSlots) {
        for (const column of meta.columns ?? []) {
          expect(
            visibleKeys.has(column.key),
            `${entry.pageKey}.${slotId}.${column.key} 已登记为可配置列，但页面没有真实显隐判断`,
          ).toBe(true)
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

  it('板块列表与详情恢复默认同时重置业务偏好和组件配置', () => {
    const listSource = sourceForPage('sectors')
    const detailSource = sourceForPage('sectors-detail')

    expect(listSource).toContain('@reset="resetSettings"')
    expect(listSource).toMatch(/function resetSettings\(\)[\s\S]*reset\(\)[\s\S]*resetLayout\(\)/)
    expect(detailSource).toContain('@reset="resetSettings"')
    expect(detailSource).toMatch(/function resetSettings\(\)[\s\S]*resetPageSettings\(\)[\s\S]*resetLayout\(\)/)
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
          (source.includes('useTableSort') && source.includes(`slotId: "${slotId}"`))
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
      const pageSizeSlots = Object.entries(entry.consumedComponentFields ?? {})
        .filter(([, fields]) => (fields ?? []).includes('pageSize'))
        .map(([slotId]) => slotId)
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
    // 父级被引用即视为消费）；settings 的解构别名（如 cfg）同样算消费入口。
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

  it('多图工作区统一声明默认比例编辑和显式设为默认入口', () => {
    for (const entry of PAGE_REGISTRY) {
      const source = sourceForPage(entry.pageKey)
      if (!source.includes('<StockChartSettingSection')) continue
      expect(source).toContain(':default-ratios="chartPreferences.defaultRatios.value"')
      expect(source).toContain('@save-default-ratios="chartPreferences.setDefaultHeightRatios"')
      expect(source).toContain('@save-current-as-default="chartPreferences.saveCurrentRatiosAsDefault"')
    }
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
