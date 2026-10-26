import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parse as parseSfc } from '@vue/compiler-sfc'
import { baseParse } from '@vue/compiler-dom'
import ts from 'typescript'

export const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
export const designContracts = JSON.parse(readFileSync(join(frontendRoot, 'scripts/design-contracts.json'), 'utf8'))

/** 所有门禁共用源文件集合；测试夹具不参与生产消费者检查。 */
export function designSources(root = join(frontendRoot, 'src')) {
  function files(dir) {
    return readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
      if (entry.name === '__tests__') return []
      const path = join(dir, entry.name)
      return entry.isDirectory() ? files(path)
        : /\.(vue|css|ts)$/.test(path) && !/\.(d|spec|test)\.ts$/.test(path) ? [path] : []
    })
  }
  return files(root).map(path => ({ file: relative(root, path).replaceAll('\\', '/'), source: readFileSync(path, 'utf8') }))
}

export function sourceParts(file, source) {
  if (!file.endsWith('.vue')) return {
    template: '', scripts: file.endsWith('.ts') ? [source] : [],
    styles: file.endsWith('.css') ? [{ content: source }] : [],
  }
  const { descriptor, errors } = parseSfc(source, { filename: file })
  if (errors.length) throw new Error(`${file}: Vue 源码无法解析`)
  return { template: descriptor.template?.content ?? '', styles: descriptor.styles,
    scripts: [descriptor.script, descriptor.scriptSetup].filter(Boolean).map(block => block.content) }
}

export function walkTemplate(template, visit) {
  function walk(node, ancestors = []) {
    if (node.type === 1) visit(node, ancestors)
    const next = node.type === 1 ? [...ancestors, node] : ancestors
    for (const child of node.children ?? []) walk(child, next)
  }
  walk(baseParse(template))
}

export function attributes(node, name) {
  return node.props.filter(p => p.type === 6 && p.name === name
    || p.type === 7 && p.name === 'bind' && p.arg?.content === name)
}

export function attributeText(prop) {
  return prop.type === 6 ? prop.value?.content ?? '' : prop.exp?.content ?? ''
}

export function scriptAst(file, source) {
  const ast = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
  if (ast.parseDiagnostics.length) throw new Error(`${file}: TS 源码无法解析`)
  return ast
}

export function walkScript(node, visit) {
  visit(node)
  ts.forEachChild(node, child => walkScript(child, visit))
}

export function literalStrings(node) {
  const strings = []
  walkScript(node, item => {
    if (ts.isStringLiteralLike(item) || ts.isTemplateHead(item)
      || ts.isTemplateMiddle(item) || ts.isTemplateTail(item)) strings.push(item.text)
  })
  return strings
}

const canonicalName = name => name.replace(/-/g, '').toLowerCase()
const entries = new Map(Object.entries(designContracts.entryPoints).map(([name, rule]) => [canonicalName(name), { name, ...rule }]))

/** 按组件来源而非变量名守卫；禁止业务方通过别名、动态组件或渲染函数绕开包装器。 */
export function auditComponentEntries(sources, inspect) {
  const violations = []
  for (const { file, source } of sources) {
    const { template, scripts } = sourceParts(file, source)
    const aliases = new Map()
    const namespaces = new Set()
    const constants = new Map()
    const asts = scripts.map(script => scriptAst(file, script))
    for (const ast of asts) walkScript(ast, node => {
      if (ts.isVariableDeclarationList(node) && node.flags & ts.NodeFlags.Const) {
        for (const declaration of node.declarations) {
          if (ts.isIdentifier(declaration.name) && declaration.initializer) constants.set(declaration.name.text, declaration.initializer)
        }
      }
    })
    const possibleNames = (node, seen = new Set()) => {
      if (!node) return []
      if (ts.isIdentifier(node) && constants.has(node.text) && !seen.has(node.text)) {
        return possibleNames(constants.get(node.text), new Set([...seen, node.text]))
      }
      if (ts.isStringLiteralLike(node)) return [node.text]
      const names = []
      ts.forEachChild(node, child => { names.push(...possibleNames(child, seen)) })
      return names
    }
    const report = (name, line = 1, root = false) => {
      inspect?.(name, file, line, root)
      const rule = entries.get(canonicalName(name))
      if (rule && rule.owner !== file) violations.push(`${file}:${line} ${rule.name} 只能由 ${rule.owner ?? '统一详情组件'} 持有；使用 ${rule.replacement}`)
    }
    for (const ast of asts) {
      walkScript(ast, node => {
        if (!ts.isImportDeclaration(node) || !ts.isStringLiteral(node.moduleSpecifier)) return
        const moduleName = node.moduleSpecifier.text
        if (moduleName.endsWith('.vue') && !node.importClause?.isTypeOnly) {
          const name = moduleName.split('/').at(-1).slice(0, -4)
          const local = node.importClause?.name?.text
          if (local) aliases.set(local, name)
          report(name)
        }
        if (!/^element-plus(?:\/|$)/.test(moduleName) || node.importClause?.isTypeOnly) return
        const bindings = node.importClause?.namedBindings
        if (bindings && ts.isNamespaceImport(bindings)) namespaces.add(bindings.name.text)
        if (bindings && ts.isNamedImports(bindings)) for (const entry of bindings.elements) {
          if (entry.isTypeOnly) continue
          const imported = (entry.propertyName ?? entry.name).text
          aliases.set(entry.name.text, imported)
          report(imported, ast.getLineAndCharacterOfPosition(entry.getStart(ast)).line + 1)
        }
        // 深路径导入也以真实库组件识别，不允许改成 default import 规避。
        const component = moduleName.match(/\/components\/([^/]+)/)?.[1]
        if (component) report(`el-${component}`)
      })
      walkScript(ast, node => {
        if (ts.isPropertyAccessExpression(node) && namespaces.has(node.expression.getText(ast))) report(node.name.text)
        if (ts.isElementAccessExpression(node) && namespaces.has(node.expression.getText(ast))) {
          if (ts.isStringLiteralLike(node.argumentExpression)) report(node.argumentExpression.text)
          else violations.push(`${file}: 动态读取 Element Plus 命名空间必须迁入对应共享入口`)
        }
        if (ts.isCallExpression(node) && /^(?:resolveComponent|h|createVNode)$/.test(node.expression.getText(ast))) {
          for (const name of possibleNames(node.arguments[0])) report(name)
        }
      })
    }
    walkTemplate(template, (node, ancestors) => {
      report(aliases.get(node.tag) ?? node.tag, node.loc.start.line, ancestors.length === 0)
      for (const prop of attributes(node, 'is')) {
        const value = attributeText(prop)
        if (prop.type === 6) report(value, node.loc.start.line)
        else {
          report(aliases.get(value) ?? value, node.loc.start.line)
          const expression = scriptAst(file, `(${value})`)
          for (const name of possibleNames(expression)) report(name, node.loc.start.line)
        }
      }
    })
  }
  return [...new Set(violations)]
}

/** 根控件包装器继续继承基础角色；专项登记不能让消费方绕过其内部真实控件。 */
export function inferStyleRoles(sources, roles = designContracts.styleRoles) {
  const byFile = new Map()
  auditComponentEntries(sources, (name, file, _line, root) => {
    if (root && file.startsWith('components/') && file.endsWith('.vue')) {
      byFile.set(file, [...(byFile.get(file) ?? []), name])
    }
  })
  // 多根片段里的弹层不是整个组合组件的根角色，不能把整块工作台误当成抽屉。
  const roots = [...byFile].filter(([, names]) => names.length === 1)
    .map(([file, names]) => ({ name: names[0], wrapper: file.split('/').at(-1).slice(0, -4) }))
  const resolved = roles.map(role => ({ ...role, tags: [...(role.tags ?? [])] }))
  let changed = true
  while (changed) {
    changed = false
    for (const role of resolved) for (const { name, wrapper } of roots) {
      if (role.tags.some(tag => canonicalName(tag) === canonicalName(name))
        && !role.tags.some(tag => canonicalName(tag) === canonicalName(wrapper))) {
        role.tags.push(wrapper)
        changed = true
      }
    }
  }
  return resolved
}

/** 基础控件必须归入受保护家族或具名专项入口；复用上面的来源解析，不能靠改 import 名绕过。 */
export function auditStyleComponents(sources, roles = designContracts.styleRoles,
  delegates = designContracts.styleDelegates ?? [], { verifyRegistry = false } = {}) {
  const violations = []
  const covered = new Set(roles.flatMap(role => role.tags ?? []).map(canonicalName))
  const inferred = new Set(inferStyleRoles(sources, roles).flatMap(role => role.tags ?? []).map(canonicalName))
  const delegated = new Map()
  const used = new Set()
  const files = new Set(sources.map(item => item.file))
  for (const [index, rule] of delegates.entries()) {
    if (!rule.reason?.trim() || !rule.tags?.length || !rule.owner) {
      violations.push('基础控件专项登记必须包含标签、持有者与依据')
      continue
    }
    if (verifyRegistry && !files.has(rule.owner)) violations.push(`${rule.owner}: 基础控件专项入口不存在`)
    for (const tag of rule.tags) {
      const name = canonicalName(tag)
      if (covered.has(name) || delegated.has(name)) violations.push(`${tag}: 基础控件样式归属重复登记`)
      delegated.set(name, index)
    }
  }
  const inspect = (name, file, line = 1, inferred = false) => {
    if (!inferred && !/^(?:el-|El[A-Z]|App[A-Z]|Page[A-Z])/.test(name)) return
    const key = canonicalName(name)
    if (covered.has(key)) return
    if (delegated.has(key)) used.add(`${delegated.get(key)}:${key}`)
    else violations.push(`${file}:${line} ${name} 尚未登记样式归属；接入 styleRoles 或具名 styleDelegates`)
  }
  auditComponentEntries(sources, (name, file, line) => inspect(name, file, line))
  for (const { file } of sources.filter(item => /\.(?:vue|ts)$/.test(item.file))) {
    const name = file.split('/').at(-1).replace(/\.(?:vue|ts)$/, '')
    // 共享命名以及直接以基础控件为根的包装器，未被消费时也检查，避免新增文件静默漏登。
    inspect(name, file, 1, inferred.has(canonicalName(name)))
  }
  if (verifyRegistry) for (const [index, rule] of delegates.entries()) for (const tag of rule.tags ?? []) {
    if (!used.has(`${index}:${canonicalName(tag)}`)) violations.push(`${tag}: 基础控件专项登记已失效`)
  }
  return [...new Set(violations)]
}
