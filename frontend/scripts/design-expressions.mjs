import { resolve } from 'node:path'
import ts from 'typescript'
import { frontendRoot, scriptAst, sourceParts, walkScript, attributes, attributeText } from './design-source.mjs'

export const UNKNOWN = Symbol('unknown expression')
export const canonicalTag = value => value.replaceAll('-', '').toLowerCase()

/** 单文件词法绑定，不加载依赖或执行用户代码；模板只回退到模块顶层绑定。 */
export function expressionContext(file, source) {
  const parts = sourceParts(file, source)
  const name = resolve(frontendRoot, 'src', `${file}.design-expressions.ts`)
  let scriptSource = source.replace(/[^\n]/g, ' ')
  let searchStart = 0
  for (const script of parts.scripts) {
    const start = source.indexOf(script, searchStart)
    scriptSource = scriptSource.slice(0,start) + script + scriptSource.slice(start + script.length)
    searchStart = start + script.length
  }
  const ast = scriptAst(name, scriptSource)
  const options = { noLib: true, noResolve: true }
  const host = ts.createCompilerHost(options)
  host.getSourceFile = path => path === name ? ast : undefined
  const checker = ts.createProgram([name], options, host).getTypeChecker()
  const globals = new Map()
  for (const statement of ast.statements) {
    if (ts.isVariableStatement(statement)) for (const declaration of statement.declarationList.declarations) {
      if (ts.isIdentifier(declaration.name)) globals.set(declaration.name.text, declaration)
    }
    if (ts.isFunctionDeclaration(statement) && statement.name) globals.set(statement.name.text, statement)
    if (!ts.isImportDeclaration(statement) || statement.importClause?.isTypeOnly) continue
    const clause = statement.importClause
    if (clause?.name) globals.set(clause.name.text, clause)
    const bindings = clause?.namedBindings
    if (bindings && ts.isNamespaceImport(bindings)) globals.set(bindings.name.text, bindings)
    if (bindings && ts.isNamedImports(bindings)) for (const entry of bindings.elements) if (!entry.isTypeOnly) globals.set(entry.name.text, entry)
  }
  const parse = text => scriptAst(file, `(${text})`).statements[0].expression
  const declaration = node => checker.getSymbolAtLocation(node)?.declarations?.[0]
    ?? (node.getSourceFile() === ast ? undefined : globals.get(node.text))
  const importInfo = node => {
    let parent = node
    while (parent && !ts.isImportDeclaration(parent)) parent = parent.parent
    if (!parent || parent.importClause?.isTypeOnly || node.isTypeOnly) return null
    return { module: parent.moduleSpecifier.text, name: ts.isImportSpecifier(node) ? (node.propertyName ?? node.name).text
      : ts.isNamespaceImport(node) ? '*' : 'default' }
  }
  const unwrap = (node, env = new Map(), seen = new Set()) => {
    if (!node || seen.has(node)) return { node, env }
    seen = new Set([...seen, node])
    if (ts.isParenthesizedExpression(node) || ts.isAsExpression(node) || ts.isSatisfiesExpression(node) || ts.isNonNullExpression(node)) return unwrap(node.expression, env, seen)
    if (ts.isIdentifier(node)) {
      const target = declaration(node)
      if (target && env.has(target)) return unwrap(env.get(target).node, env.get(target).env, seen)
      if (target && ts.isVariableDeclaration(target) && target.initializer
        && (target.parent.flags & ts.NodeFlags.Const)) return unwrap(target.initializer, env, seen)
      return { node: target ?? node, env }
    }
    return { node, env }
  }
  const origin = (node, env = new Map()) => {
    const resolved = unwrap(node, env)
    if (!resolved.node) return null
    const imported = importInfo(resolved.node)
    if (imported) return imported
    if (ts.isPropertyAccessExpression(resolved.node) || ts.isElementAccessExpression(resolved.node)) {
      const parent = origin(resolved.node.expression, resolved.env)
      const key = ts.isPropertyAccessExpression(resolved.node) ? resolved.node.name.text
        : ts.isStringLiteralLike(resolved.node.argumentExpression) ? resolved.node.argumentExpression.text : ''
      return parent?.name === '*' ? {module:parent.module,name:key} : null
    }
    return null
  }
  const vueCall = node => {
    if (!ts.isCallExpression(node)) return ''
    const info = origin(node.expression)
    if (info?.module === 'vue' && ['computed', 'ref', 'shallowRef', 'reactive'].includes(info.name)) return info.name
    // 小夹具与显式自动导入可省略 import；局部同名函数不能冒充 Vue 入口。
    if (ts.isIdentifier(node.expression) && !declaration(node.expression)
      && ['computed', 'ref', 'shallowRef', 'reactive'].includes(node.expression.text)) return node.expression.text
    return ''
  }
  const returns = (call, env = new Map()) => {
    const target = unwrap(call.expression, env)
    const fn = target.node
    if (!fn || !(ts.isFunctionDeclaration(fn) || ts.isArrowFunction(fn) || ts.isFunctionExpression(fn)) || !fn.body) return []
    const bindings = new Map(target.env)
    fn.parameters.forEach((parameter, index) => {
      const argument = call.arguments[index] ?? parameter.initializer
      if (argument) bindings.set(parameter, {node:argument,env})
    })
    if (!ts.isBlock(fn.body)) return [{node:fn.body,env:bindings}]
    const values = []
    const walk = node => {
      if (node !== fn.body && (ts.isFunctionLike(node))) return
      if (ts.isReturnStatement(node) && node.expression) values.push({node:node.expression,env:bindings})
      ts.forEachChild(node, walk)
    }
    walk(fn.body)
    return values
  }
  const combine = (groups, build) => {
    let choices = [[]]
    for (const group of groups) {
      if (choices.length * group.length > 64) return [UNKNOWN]
      choices = choices.flatMap(choice => group.map(value => [...choice, value]))
    }
    return choices.map(build)
  }
  const keyOf = (name, env) => {
    if (ts.isComputedPropertyName(name)) return values(name.expression, env).find(value => typeof value === 'string')
    return name.text
  }
  /** 有限字面量求值保留对象展开顺序；未知调用不猜结果，也不提取调用参数冒充输出。 */
  const values = (input, env = new Map(), seen = new Set()) => {
    const resolved = unwrap(input, env)
    const node = resolved.node
    env = resolved.env
    if (!node || seen.has(node)) return [UNKNOWN]
    seen = new Set([...seen, node])
    const read = child => values(child, env, seen)
    if (ts.isStringLiteralLike(node)) return [node.text]
    if (ts.isNumericLiteral(node)) return [Number(node.text)]
    if (node.kind === ts.SyntaxKind.TrueKeyword) return [true]
    if (node.kind === ts.SyntaxKind.FalseKeyword) return [false]
    if (node.kind === ts.SyntaxKind.NullKeyword) return [null]
    if (ts.isPrefixUnaryExpression(node) && [ts.SyntaxKind.MinusToken, ts.SyntaxKind.PlusToken].includes(node.operator)) return read(node.operand).map(value => typeof value === 'number' ? node.operator === ts.SyntaxKind.MinusToken ? -value : value : UNKNOWN)
    if (ts.isConditionalExpression(node)) return [...read(node.whenTrue), ...read(node.whenFalse)]
    if (ts.isTemplateExpression(node)) return combine(node.templateSpans.map(span => read(span.expression)), parts => node.head.text + node.templateSpans.map((span, index) => `${parts[index] === UNKNOWN ? '' : parts[index]}${span.literal.text}`).join(''))
    if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken) return combine([read(node.left),read(node.right)], ([a,b]) => typeof a === 'string' || typeof b === 'string' ? `${a === UNKNOWN ? '' : a}${b === UNKNOWN ? '' : b}` : a !== UNKNOWN && b !== UNKNOWN ? a + b : UNKNOWN)
    if (ts.isArrayLiteralExpression(node)) return combine(node.elements.map(read), parts => parts)
    if (ts.isObjectLiteralExpression(node)) {
      let objects = [{}]
      for (const prop of node.properties) {
        if (ts.isSpreadAssignment(prop)) {
          objects = combine([objects, read(prop.expression)], ([a,b]) => ({...a,...(b !== UNKNOWN && b && typeof b === 'object' ? b : {})}))
        } else if (ts.isPropertyAssignment(prop) || ts.isShorthandPropertyAssignment(prop)) {
          const key = keyOf(prop.name, env)
          if (key != null) objects = combine([objects,read(prop.initializer ?? prop.name)], ([a,b]) => ({...a,[key]:b}))
        }
      }
      return objects
    }
    if (ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node)) {
      if (ts.isPropertyAccessExpression(node) && node.name.text === 'value') {
        const reference = unwrap(node.expression,env).node
        if (reference && ts.isCallExpression(reference) && vueCall(reference)) return read(node.expression)
      }
      const keys = ts.isPropertyAccessExpression(node) ? [node.name.text] : read(node.argumentExpression)
      return combine([read(node.expression),keys], ([object,key]) => object !== UNKNOWN && object != null && key !== UNKNOWN ? object[key] ?? UNKNOWN : UNKNOWN)
    }
    if (ts.isCallExpression(node)) {
      const vue = vueCall(node)
      if (vue === 'computed') {
        const callback = node.arguments[0]
        return callback && ts.isArrowFunction(callback) && !ts.isBlock(callback.body) ? read(callback.body) : [UNKNOWN]
      }
      if (vue) return node.arguments[0] ? read(node.arguments[0]) : [UNKNOWN]
      if (node.expression.getText() === 'Object.freeze') return read(node.arguments[0])
      const result = returns(node, env)
      if (result.length) return result.flatMap(entry => values(entry.node, entry.env, seen))
      if (ts.isPropertyAccessExpression(node.expression) && ['replace','replaceAll','slice','substring','trim'].includes(node.expression.name.text)) {
        return combine([read(node.expression.expression), ...node.arguments.map(read)], ([base,...args]) => {
          if (typeof base !== 'string' || args.includes(UNKNOWN)) return UNKNOWN
          return base[node.expression.name.text](...args)
        })
      }
    }
    return [UNKNOWN]
  }
  const component = (text, seen = new Set()) => {
    if (!/^(?:[\w$]+(?:\.[\w$]+)*|['"].*['"])$/.test(text)) return canonicalTag(text)
    const node = parse(text)
    const info = origin(node)
    if (info?.module.endsWith('.vue')) return canonicalTag(info.module.split('/').at(-1).slice(0,-4))
    if (info && /^element-plus(?:\/|$)/.test(info.module)) {
      if (info.name !== 'default') return canonicalTag(info.name)
      const name = info.module.match(/\/components\/([^/]+)/)?.[1]
      if (name) return canonicalTag(`el-${name}`)
    }
    const value = values(node).find(value => typeof value === 'string')
    if (typeof value === 'string' && !seen.has(value)) return component(value, new Set([...seen,value]))
    return canonicalTag(text.replace(/^['"]|['"]$/g, ''))
  }
  const tag = node => node.tag === 'component' && attributes(node,'is')[0]
    ? component(attributeText(attributes(node,'is')[0])) : component(node.tag)
  const props = node => {
    let objects = [{}]
    for (const prop of node.props) {
      if (prop.type === 6) objects = objects.map(object => ({...object,[prop.name]:prop.value?.content ?? true}))
      if (prop.type !== 7 || prop.name !== 'bind' || !prop.exp) continue
      const results = values(parse(prop.exp.content))
      if (!prop.arg) objects = combine([objects,results], ([a,b]) => ({...a,...(b !== UNKNOWN && b && typeof b === 'object' ? b : {})}))
      else if (prop.arg.isStatic) objects = combine([objects,results], ([a,b]) => ({...a,[prop.arg.content]:b}))
    }
    return objects
  }
  const line = number => number + (parts.template ? source.slice(0,source.indexOf(parts.template)).split('\n').length - 1 : 0)
  return {...parts, file, ast, parse, declaration, unwrap, origin, values, returns, vueCall, globals, keyOf, component, tag, props, line}
}
