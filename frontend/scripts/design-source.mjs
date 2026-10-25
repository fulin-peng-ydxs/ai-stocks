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
export function auditComponentEntries(sources) {
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
    const report = (name, line = 1) => {
      const rule = entries.get(canonicalName(name))
      if (rule && rule.owner !== file) violations.push(`${file}:${line} ${rule.name} 只能由 ${rule.owner ?? '统一详情组件'} 持有；使用 ${rule.replacement}`)
    }
    for (const ast of asts) {
      walkScript(ast, node => {
        if (!ts.isImportDeclaration(node) || !ts.isStringLiteral(node.moduleSpecifier)) return
        const moduleName = node.moduleSpecifier.text
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
    walkTemplate(template, node => {
      report(aliases.get(node.tag) ?? node.tag, node.loc.start.line)
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
