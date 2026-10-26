import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import postcss from 'postcss'
import ts from 'typescript'
import {
  attributeText, attributes, auditComponentEntries, auditStyleComponents, designContracts, designSources,
  frontendRoot, inferStyleRoles, literalStrings, scriptAst, sourceParts, walkScript, walkTemplate,
} from './design-source.mjs'

const nodeClassCache = new WeakMap()
const classesOf = node => {
  if (nodeClassCache.has(node)) return nodeClassCache.get(node)
  const names = attributes(node, 'class').flatMap(prop => {
    if (prop.type === 6) return attributeText(prop).split(/\s+/)
    const ast = scriptAst('class.ts', `(${attributeText(prop)})`)
    return literalStrings(ast).flatMap(value => value.split(/\s+/))
  }).filter(Boolean)
  nodeClassCache.set(node, names)
  return names
}
const cssClasses = selector => [...selector.matchAll(/\.([_a-zA-Z][\w-]*)/g)].map(match => match[1])
const staticClassesOf = node => attributes(node, 'class').filter(prop => prop.type === 6)
  .flatMap(prop => attributeText(prop).split(/\s+/))
const canonicalTag = tag => tag.replaceAll('-', '').toLowerCase()
const roleClasses = role => [role.className, ...(role.classNames ?? [])]
const matchesRole = (node, role) => classesOf(node).some(name => roleClasses(role).includes(name))
  || role.tags?.some(tag => canonicalTag(tag) === canonicalTag(node.tag))

function nestingDepth(text) {
  let depth = 0, quote = ''
  for (const char of text) {
    if (quote) { if (char === quote) quote = ''; continue }
    if (char === '"' || char === "'") { quote = char; continue }
    if (char === '(' || char === '[') depth++
    if (char === ')' || char === ']') depth--
  }
  return depth
}

function withoutHas(selector) {
  let result = selector
  for (let start = result.indexOf(':has('); start >= 0; start = result.indexOf(':has(')) {
    let end = start + 5
    while (end < result.length && nestingDepth(result.slice(start, end + 1)) > 0) end++
    result = result.slice(0, start) + result.slice(end + 1)
  }
  return result
}

function roleTargets(template, roles = designContracts.styleRoles) {
  const targets = []
  walkTemplate(template, (node, ancestors) => {
    const classes = classesOf(node)
    for (const role of roles) {
      const scope = roles.find(candidate => candidate.className === role.within)
      if (scope && !ancestors.some(item => matchesRole(item, scope))) continue
      const root = [node, ...ancestors].find(item => matchesRole(item, role))
      if (root && (root === node || role.descendants)) targets.push({ node, role,
        classes: [...classes, ...(root === node ? [role.className] : [])],
        exclusions: [...staticClassesOf(node), ...(root === node ? [role.className] : [])],
        ancestors: ancestors.flatMap(classesOf) })
    }
  })
  return targets
}

function protectedProperty(role, property) {
  if (!property.startsWith('--')) property = property.toLowerCase()
  return property === 'all' || role.properties.includes(property)
    || role.properties.includes('font') && property.startsWith('font-')
    || role.properties.includes('padding') && property.startsWith('padding-')
    || role.properties.includes('background') && property.startsWith('background-')
    || role.properties.includes('border') && /^border-(?:top|right|bottom|left)(?:-(?:color|width|style))?$/.test(property)
}

/** 使用选择器中的角色/别名及后代关系判断覆盖，不剥离伪类后再靠 DOM 偶然匹配。 */
function targetsSelector(selector, target) {
  const globallyApplied = selector.includes(':global(')
  // Vue 的 deep/global 包装不改变最终样式目标；先展开再判断末端，避免把子文字当成按钮根。
  for (const name of ['deep', 'global']) {
    const prefix = `:${name}(`
    for (let start = selector.indexOf(prefix); start >= 0; start = selector.indexOf(prefix)) {
      let end = start + prefix.length
      while (end < selector.length && nestingDepth(selector.slice(start, end + 1)) > 0) end++
      if (end >= selector.length) break
      selector = selector.slice(0, start) + selector.slice(start + prefix.length, end) + selector.slice(end + 1)
    }
  }
  // 只检查选择器真正作用的末端元素；相邻兄弟和 :has() 内的条件不是样式目标。
  let subject = '', depth = 0, quote = ''
  for (const char of selector.trim()) {
    if (quote) { subject += char; if (char === quote) quote = ''; continue }
    if (char === '"' || char === "'") { quote = char; subject += char; continue }
    if (char === '(' || char === '[') depth++
    if (char === ')' || char === ']') depth--
    if (!depth && /[\s>+~]/.test(char)) subject = ''
    else subject += char
  }
  subject = withoutHas(subject)
  // .cell 等通用名称只在表格上下文中受控，不能误伤指标条等独立组件的同名类。
  if (target.contexts && !globallyApplied
    && !cssClasses(selector.slice(0, selector.length - subject.length)).some(name => target.contexts.includes(name))) return false
  // 装饰伪元素的尺寸属于组件几何，不是按钮自身的尺寸覆盖。
  if (/::(?:before|after|marker)\b/.test(subject)) return false
  // 明确排除该角色的普通名称样式不属于覆盖；排除条件不能含组合器或其它状态。
  for (const match of subject.matchAll(/:not\(([^()]+)\)/g)) {
    if (nestingDepth(subject.slice(0, match.index)) > 0) continue
    if (match[1].split(',').some(value => target.exclusions.includes(value.trim().match(/^\.([\w-]+)$/)?.[1]))) return false
  }
  const classes = cssClasses(subject)
  // is-active 等通用状态名不能把无关的另一种组件认作同一控件。
  const identities = classes.filter(name => !/^(?:is|has)-/.test(name))
  if ((identities.length ? identities : classes).some(name => target.classes.includes(name))) return true
  const tag = subject.match(/^[a-z][\w-]*/i)?.[0]
  // input/textarea 是库组件生成的真实内层，也须沿调用方别名追踪，不能只识别 .el-* 类。
  if (tag && target.role.innerTags?.includes(tag)
    && (!cssClasses(selector).length || cssClasses(selector.slice(0, -subject.length))
      .some(name => [...target.classes, ...target.ancestors].includes(name)))) return true
  return !!tag && (tag === target.node.tag || tag === target.role.elementTag
    && target.role.tags?.some(name => canonicalTag(name) === canonicalTag(target.node.tag))) && (!cssClasses(selector).length
    || cssClasses(selector).some(name => target.ancestors.includes(name)))
}

export function auditSharedStyles(sources, roles = designContracts.styleRoles, { verifyOwners = false } = {}) {
  roles = inferStyleRoles(sources, roles)
  const violations = []
  const usedOwners = new Set()
  const prepared = sources.map(item => {
    const parts = sourceParts(item.file, item.source)
    return { ...item, ...parts, targets: roleTargets(parts.template, roles) }
  })
  const externalTargets = prepared.flatMap(item => item.targets)
  for (const item of prepared) {
    // all 会同时重置多个角色属性；不允许用通配选择器、普通结构节点或登记例外绕过。
    for (const style of item.styles) postcss.parse(style.content).walkDecls(decl => {
      if (decl.prop.toLowerCase() === 'all') violations.push(`${item.file}: ${decl.parent.selector ?? '<style>'} 禁止使用 all 重置共享样式`)
    })
    walkTemplate(item.template, node => {
      const names = new Set(['style', ...roles.flatMap(role => role.styleAttributes ?? [])])
      for (const prop of [...names].flatMap(name => attributes(node, name))) {
        const value = attributeText(prop)
        const reportReset = () => violations.push(`${item.file}: <${node.tag}> 禁止使用 all 重置共享样式`)
        if (prop.type === 6) postcss.parse(`x{${value}}`).walkDecls(decl => {
          if (decl.prop.toLowerCase() === 'all') reportReset()
        })
        else walkScript(scriptAst(item.file, `(${value})`), part => {
          if (ts.isPropertyAssignment(part) || ts.isShorthandPropertyAssignment(part)) {
            const name = ts.isComputedPropertyName(part.name) && ts.isStringLiteralLike(part.name.expression)
              ? part.name.expression.text : part.name.getText().replace(/['"]/g, '')
            if (name.toLowerCase() === 'all') reportReset()
          }
          if (ts.isStringLiteralLike(part) && /(?:^|;)\s*all\s*:/i.test(part.text)) reportReset()
        })
      }
    })
    const targets = (item.file.endsWith('.css') ? externalTargets : item.targets)
      .filter(target => roles.some(role => role.className === target.role.className))
    // 已登记的根角色也拦截仅有 :deep()/外部选择器、没有本地模板实例的覆盖。
    for (const role of roles.filter(role => role.owners)) {
      const scope = roles.find(candidate => candidate.className === role.within)
      const contexts = scope && !item.file.endsWith('.css') ? [
        ...roleClasses(scope),
        ...externalTargets.filter(target => target.role === scope).flatMap(target => [...target.classes, ...target.ancestors]),
      ] : undefined
      for (const name of roleClasses(role)) targets.push({
        node: { tag: '', props: [] }, role, classes: [name], exclusions: [name], ancestors: [], contexts,
      })
    }
    const report = (selector, property) => violations.push(`${item.file}: ${selector} 不得私设 ${property}；使用共享角色入口`)
    const allowed = (role, selector, property) => {
      if (property === 'all') return false
      if (!role.owners) return item.file === 'styles/global.css'
      return role.owners.some((owner, index) => {
        if (owner.file !== item.file || !owner.selectors.includes(selector)
          || !owner.properties.includes(property) || !owner.reason?.trim()) return false
        usedOwners.add(`${role.className}:${index}:${selector}:${property}`)
        return true
      })
    }
    const allowsBinding = (target, prop) => (target.role.bindings ?? []).some((binding, index) => {
      const name = prop.arg ? prop.arg.content : 'attrs'
      if (binding.file !== item.file || canonicalTag(binding.tag) !== canonicalTag(target.node.tag)
        || binding.name !== name || binding.expression !== attributeText(prop) || !binding.reason?.trim()) return false
      usedOwners.add(`${target.role.className}:binding:${index}`)
      return true
    })
    for (const style of item.styles) postcss.parse(style.content).walkRules(rule => {
      for (const target of targets) {
        if (!rule.selectors.some(selector => targetsSelector(selector, target))) continue
        rule.walkDecls(decl => {
          if (protectedProperty(target.role, decl.prop) && !allowed(target.role, rule.selector, decl.prop)) report(rule.selector, decl.prop)
        })
      }
    })
    // 外部 CSS 借模板识别消费类，但绑定必须在模板所属文件校验，不能把 CSS 文件当成透传者。
    for (const target of item.targets) {
      for (const prop of (target.role.styleAttributes ?? ['style']).flatMap(name => attributes(target.node, name))) {
        if (prop.type === 6) postcss.parse(`x{${attributeText(prop)}}`).walkDecls(decl => {
          if (protectedProperty(target.role, decl.prop) && !allowed(target.role, '<inline style>', decl.prop)) report('<inline style>', decl.prop)
        })
        else {
          // 唯一适配器可以透传自身属性/计算几何，消费方不能借同名表达式获得授权。
          if (allowsBinding(target, prop)) continue
          const expression = attributeText(prop)
          if (!expression.trim().startsWith('{')) {
            report('<dynamic style>', '不可静态确认的样式绑定')
            continue
          }
          const ast = scriptAst(item.file, `(${expression})`)
          walkScript(ast, node => {
            if (ts.isPropertyAssignment(node) || ts.isShorthandPropertyAssignment(node)) {
              if (ts.isComputedPropertyName(node.name)) {
                report('<dynamic style>', '不可静态确认的样式属性名')
                return
              }
              const key = node.name.getText(ast).replace(/['"]/g, '').replace(/[A-Z]/g, c => `-${c.toLowerCase()}`)
              if (protectedProperty(target.role, key)) report('<dynamic style>', key)
            }
            if (ts.isSpreadAssignment(node)) report('<dynamic style>', '展开样式')
          })
        }
      }
      for (const prop of target.node.props.filter(prop => prop.type === 7 && prop.name === 'bind' && !prop.arg)) {
        if (!allowsBinding(target, prop)) report('<v-bind>', '整包属性绑定')
      }
    }
  }
  if (verifyOwners) for (const role of roles) {
    for (const [index, binding] of (role.bindings ?? []).entries()) {
      if (!usedOwners.has(`${role.className}:binding:${index}`)) {
        violations.push(`${binding.file}: ${binding.tag} 的 ${role.className} ${binding.name} 绑定归属已失效`)
      }
    }
    for (const [index, owner] of (role.owners ?? []).entries()) {
      if (!owner.reason?.trim() || !owner.selectors.length || !owner.properties.length) {
        violations.push(`${role.className}: 样式持有者必须登记精确选择器、属性与语义依据`)
      }
      for (const selector of owner.selectors) for (const property of owner.properties) {
        if (!usedOwners.has(`${role.className}:${index}:${selector}:${property}`)) {
          violations.push(`${owner.file}: ${selector} 的 ${role.className}.${property} 样式归属登记已失效`)
        }
      }
    }
  }
  return [...new Set(violations)]
}

/** 运行时样式写入默认拒绝；主题、缩放、浮层和测量仅按目标、操作与属性授权。 */
export function auditRuntimeStyles(sources, owners = designContracts.runtimeStyleOwners ?? [], { verifyOwners = false } = {}) {
  const violations = []
  const used = new Set()
  const normalize = name => name.startsWith('--') ? name : name.replace(/[A-Z]/g, c => `-${c.toLowerCase()}`)
  const unwrap = node => {
    while (node && (ts.isParenthesizedExpression(node) || ts.isAsExpression(node)
      || ts.isTypeAssertionExpression(node) || ts.isNonNullExpression(node))) node = node.expression
    return node
  }
  const member = node => {
    node = unwrap(node)
    if (node && ts.isPropertyAccessExpression(node)) return { object: node.expression, key: node.name.text }
    if (node && ts.isElementAccessExpression(node)) return { object: node.expression,
      key: ts.isStringLiteralLike(node.argumentExpression) ? node.argumentExpression.text : null }
    return null
  }
  for (const { file, source } of sources) for (const script of sourceParts(file, source).scripts) {
    const ast = scriptAst(file, script)
    const aliases = new Map()
    const renderNames = new Set(['h', 'createVNode', 'createElementVNode'])
    const vueNamespaces = new Set()
    const remember = (name, value) => aliases.set(name, [...(aliases.get(name) ?? []), value])
    walkScript(ast, node => {
      if (ts.isImportDeclaration(node) && node.moduleSpecifier.text === 'vue') {
        const bindings = node.importClause?.namedBindings
        if (bindings && ts.isNamespaceImport(bindings)) vueNamespaces.add(bindings.name.text)
        if (bindings && ts.isNamedImports(bindings)) for (const entry of bindings.elements) {
          if (['h', 'createVNode', 'createElementVNode'].includes((entry.propertyName ?? entry.name).text)) renderNames.add(entry.name.text)
        }
      }
      if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) remember(node.name.text, node.initializer)
      if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.EqualsToken
        && ts.isIdentifier(node.left)) remember(node.left.text, node.right)
    })
    const resolve = (node, seen = new Set()) => {
      node = unwrap(node)
      if (node && ts.isIdentifier(node) && aliases.get(node.text)?.length === 1 && !seen.has(node.text)) {
        return resolve(aliases.get(node.text)[0], new Set([...seen, node.text]))
      }
      return node
    }
    const styleRef = (node, seen = new Set()) => {
      node = unwrap(node)
      if (!node) return null
      if (ts.isIdentifier(node) && aliases.has(node.text) && !seen.has(node.text)) {
        return aliases.get(node.text).map(value => styleRef(value, new Set([...seen, node.text]))).find(Boolean) ?? null
      }
      const access = member(node)
      return access?.key === 'style' ? `${access.object.getText(ast)}.style` : null
    }
    const literal = node => {
      node = resolve(node)
      return node && ts.isStringLiteralLike(node) ? node.text : null
    }
    const report = (node, operation, target, properties = []) => {
      const expression = node.getText(ast)
      const keys = properties.map(normalize)
      const allowed = owners.some((owner, index) => {
        if (owner.file !== file || owner.operation !== operation || owner.target !== target || !owner.reason?.trim()) return false
        if (keys.includes('all')) return false
        if (owner.expression ? owner.expression !== expression
          : !keys.length || keys.some(key => !owner.properties?.includes(key))) return false
        used.add(`${index}:used`)
        for (const key of keys) used.add(`${index}:${key}`)
        return true
      })
      if (!allowed) violations.push(`${file}:${ast.getLineAndCharacterOfPosition(node.getStart(ast)).line + 1} 未授权运行时样式 ${operation} ${target} ${keys.join(',') || '<动态/整包>'}；使用共享呈现或精确登记`)
    }
    const objectKeys = node => {
      node = resolve(node)
      if (!node || !ts.isObjectLiteralExpression(node)) return []
      const keys = []
      for (const property of node.properties) {
        if (!property.name || ts.isComputedPropertyName(property.name)) return []
        keys.push(property.name.getText(ast).replace(/['"]/g, ''))
      }
      return keys
    }
    const isStyleElement = node => {
      node = resolve(node)
      return node && ts.isCallExpression(node) && /(?:createElement|querySelector)$/.test(node.expression.getText(ast))
        && literal(node.arguments[0]) === 'style'
    }
    const styleProps = new Set(['style', ...designContracts.styleRoles.flatMap(role => role.styleAttributes ?? [])].map(canonicalTag))
    const inspectRenderProps = (node, target, anchor = node) => {
      const value = resolve(node)
      // h 的第二参也可承载纯文本、子节点或插槽；这些不是可变样式属性。
      if (value && (ts.isStringLiteralLike(value) || ts.isNumericLiteral(value)
        || ts.isArrayLiteralExpression(value) || ts.isArrowFunction(value) || ts.isFunctionExpression(value)
        || value.kind === ts.SyntaxKind.NullKeyword || value.getText(ast) === 'undefined')) return
      if (value && ts.isConditionalExpression(value)) {
        inspectRenderProps(value.whenTrue, target, anchor)
        inspectRenderProps(value.whenFalse, target, anchor)
      } else if (value && ts.isObjectLiteralExpression(value)) {
        for (const property of value.properties) {
          if (ts.isSpreadAssignment(property)) inspectRenderProps(property.expression, target, property)
          else if (property.name && (ts.isComputedPropertyName(property.name)
            || styleProps.has(canonicalTag(property.name.getText(ast).replace(/['"]/g, ''))))) report(property, 'renderStyle', target)
        }
      } else if (value) {
        report(anchor, 'renderProps', target)
      }
    }
    walkScript(ast, node => {
      const mutation = ts.isBinaryExpression(node) && node.operatorToken.kind >= ts.SyntaxKind.FirstAssignment
        && node.operatorToken.kind <= ts.SyntaxKind.LastAssignment ? node.left
        : ts.isDeleteExpression(node) ? node.expression
          : (ts.isPrefixUnaryExpression(node) || ts.isPostfixUnaryExpression(node))
            && [ts.SyntaxKind.PlusPlusToken, ts.SyntaxKind.MinusMinusToken].includes(node.operator) ? node.operand : null
      if (mutation) {
        const access = member(mutation)
        const target = styleRef(access?.object)
        if (target) report(node, 'write', target, access.key ? [access.key] : [])
        else if (access?.key === 'style') report(node, 'replace', styleRef(mutation))
        else if (access?.key === 'adoptedStyleSheets') report(node, 'stylesheet', access.object.getText(ast))
        else if (access && ['textContent', 'innerHTML', 'innerText'].includes(access.key) && isStyleElement(access.object)) {
          report(node, 'stylesheet', access.object.getText(ast))
        }
      }
      if (ts.isVariableDeclaration(node) && ts.isObjectBindingPattern(node.name) && styleRef(node.initializer)) {
        if (node.name.elements.some(item => ['setProperty', 'removeProperty'].includes((item.propertyName ?? item.name).getText(ast)))) {
          report(node, 'extract', styleRef(node.initializer))
        }
      }
      if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name)) {
        const access = member(node.initializer)
        if (access && styleRef(access.object) && (access.key === null || ['setProperty', 'removeProperty'].includes(access.key))) {
          report(node, 'extract', styleRef(access.object))
        }
      }
      if ((ts.isReturnStatement(node) || ts.isPropertyAssignment(node)) && styleRef(node.expression ?? node.initializer)) {
        report(node, 'escape', styleRef(node.expression ?? node.initializer))
      }
      if (ts.isArrowFunction(node) && styleRef(node.body)) report(node, 'escape', styleRef(node.body))
      if (ts.isArrayLiteralExpression(node)) for (const element of node.elements) {
        if (styleRef(element)) report(element, 'escape', styleRef(element))
      }
      if (!ts.isCallExpression(node)) return
      const access = member(node.expression)
      const callee = resolve(node.expression)
      if (renderNames.has(callee?.getText(ast)) || access && vueNamespaces.has(access.object.getText(ast)) && renderNames.has(access.key)) {
        if (node.arguments[1]) inspectRenderProps(node.arguments[1], node.expression.getText(ast))
      }
      const target = access && styleRef(access.object)
      if (target) {
        if (['getPropertyValue', 'getPropertyPriority', 'item', 'toString'].includes(access.key)) return
        const key = literal(node.arguments[0])
        report(node, access.key ?? 'dynamicCall', target, key ? [key] : [])
        return
      }
      const attributeIndex = access?.key === 'setAttributeNS' ? 1 : 0
      const attributeName = literal(node.arguments[attributeIndex])?.toLowerCase() ?? null
      if (access && ['setAttribute', 'setAttributeNS', 'removeAttribute', 'toggleAttribute'].includes(access.key)
        && (attributeName === 'style' || attributeName === null)) {
        report(node, access.key, access.object.getText(ast))
        return
      }
      if (['Object.assign', 'Object.defineProperty', 'Object.defineProperties', 'Reflect.set', 'Reflect.deleteProperty'].includes(node.expression.getText(ast))
        && styleRef(node.arguments[0])) {
        const assignments = node.arguments.slice(1).map(objectKeys)
        report(node, node.expression.getText(ast), styleRef(node.arguments[0]),
          node.expression.getText(ast) === 'Object.assign' ? assignments.every(keys => keys.length) ? assignments.flat() : []
            : node.expression.getText(ast) === 'Object.defineProperties' ? objectKeys(node.arguments[1])
            : literal(node.arguments[1]) ? [literal(node.arguments[1])] : [])
        return
      }
      if (access && (['insertRule', 'deleteRule', 'addRule', 'replaceSync'].includes(access.key)
        || access.key === 'replace' && /(?:CSSStyleSheet|styleSheets|\.sheet\b)/.test(resolve(access.object)?.getText(ast) ?? '')
        || /(?:adoptedStyleSheets|styleSheets)/.test(access.object.getText(ast)))) {
        report(node, 'stylesheet', access.object.getText(ast))
        return
      }
      for (const argument of node.arguments) if (styleRef(argument)) report(node, 'escape', styleRef(argument))
    })
  }
  if (verifyOwners) for (const [index, owner] of owners.entries()) {
    if (!owner.reason?.trim() || !owner.target || !owner.operation || (!owner.expression && !owner.properties?.length)) {
      violations.push(`${owner.file}: 运行时样式授权必须登记目标、操作、属性或精确表达式以及依据`)
    }
    if (!used.has(`${index}:used`)) violations.push(`${owner.file}: ${owner.target} ${owner.operation} 运行时样式授权已失效`)
    if (!owner.expression) for (const property of owner.properties ?? []) {
      if (!used.has(`${index}:${property}`)) violations.push(`${owner.file}: ${owner.target}.${property} 运行时样式授权已失效`)
    }
  }
  return [...new Set(violations)]
}

// 只剥离完整 var()，并列写死的其它颜色仍须检查。
function withoutVariables(value) {
  let result = ''
  for (let index = 0; index < value.length; index++) {
    if (value.slice(index, index + 4) !== 'var(') { result += value[index]; continue }
    let depth = 1
    index += 4
    while (index < value.length && depth) {
      if (value[index] === '(') depth++
      if (value[index] === ')') depth--
      index++
    }
    index--
  }
  return result
}
const colorLiteral = /#[\da-f]{3,8}\b|(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\s*\(|\b(?:white|black|red|blue|green|yellow|orange|purple|gray|grey)\b/i
const colorProperty = /^(?:color|background(?:-.+)?|border(?:-.+)?|outline(?:-.+)?|(?:box|text)-shadow|fill|stroke|accent-color|caret-color|--.+)$/

function inThemeFallback(node) {
  for (let parent = node.parent; parent; parent = parent.parent) {
    if (ts.isCallExpression(parent) && parent.expression.getText() === 'chartCssVariable'
      && parent.arguments[0] && ts.isStringLiteralLike(parent.arguments[0])
      && parent.arguments[0].text.startsWith('--')) return true
  }
  return false
}

/** 颜色源按精确声明登记；普通 CSS、模板绑定、TS 对象与运行时样式使用同一判据。 */
export function auditColorSources(sources, exceptions = designContracts.colorExceptions) {
  const violations = []
  const used = new Set()
  const allowed = (file, selector, property, value) => {
    const key = exceptions.findIndex(entry => entry.file === file && entry.selector === selector
      && entry.property === property && (entry.values ?? [entry.value]).includes(value) && entry.reason?.trim())
    if (key >= 0) used.add(`${key}:${value}`)
    return key >= 0
  }
  for (const { file, source } of sources) {
    const parts = sourceParts(file, source)
    const inspect = (selector, property, value) => {
      let remainder = withoutVariables(value)
      // 与主题色混合的中性黑白是调色运算，不是第二套语义色板。
      if (value.includes('var(') && /(?:color-mix|gradient)\(/.test(value)) remainder = remainder.replace(/\b(?:white|black)\b/g, '')
      if (!colorProperty.test(property) || !colorLiteral.test(remainder)) return
      if (file === 'styles/global.css' && property.startsWith('--') && !/^--(?:market-|score-|app-(?:warning|danger))/.test(property)) return
      if (allowed(file, selector, property, value)) return
      violations.push(`${file}: ${selector} ${property}: ${value} 含私有颜色；使用主题 token 或登记精确图形例外`)
    }
    for (const style of parts.styles) postcss.parse(style.content).walkDecls(decl => {
      inspect(decl.parent.selector ?? '', decl.prop, decl.value)
    })
    walkTemplate(parts.template, node => {
      for (const prop of attributes(node, 'style')) {
        if (prop.type === 6) postcss.parse(`x{${attributeText(prop)}}`).walkDecls(decl => inspect('<inline style>', decl.prop, decl.value))
        else {
          const ast = scriptAst(file, `(${attributeText(prop)})`)
          walkScript(ast, item => {
            if (ts.isStringLiteralLike(item) && colorLiteral.test(item.text)) inspect('<dynamic style>', 'color', item.text)
          })
        }
      }
    })
    // token 定义是唯一色板；业务脚本及 tooltip 字符串也不能平行维护色值。
    if (['layout/presets.ts', 'layout/themeSurfaces.ts'].includes(file)) continue
    for (const script of parts.scripts) {
      const ast = scriptAst(file, script)
      walkScript(ast, node => {
        if (!(ts.isStringLiteralLike(node) || ts.isTemplateHead(node) || ts.isTemplateMiddle(node) || ts.isTemplateTail(node))
          || !colorLiteral.test(node.text) || inThemeFallback(node)) return
        // 文案/选择器不是颜色；纯色字符串和 HTML 内联样式才纳入色值检查。
        if (/^(?:#[\da-f]{3,8}|(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\s*\([^<>]+\)|white|black|red|blue|green|yellow|orange|purple|gray|grey)$/i.test(node.text)) {
          let symbol = ''
          for (let parent = node.parent; parent; parent = parent.parent) {
            if (ts.isFunctionDeclaration(parent) && parent.name) { symbol = parent.name.text; break }
            if (ts.isVariableDeclaration(parent) && parent.name) symbol = parent.name.getText(ast)
          }
          inspect(`<script:${symbol}>`, 'color', node.text)
        } else for (const match of node.text.matchAll(/(?:color|background(?:-color)?|border(?:-color)?)\s*:\s*([^;"'<>]+)/g)) {
          inspect('<script style>', 'color', match[1])
        }
      })
    }
  }
  // 全树执行才拒绝过期例外；单文件小夹具不承担全树清单完整性。
  if (sources.some(item => item.file === 'styles/global.css')) exceptions.forEach((entry, index) => {
    for (const value of entry.values ?? [entry.value]) {
      if (!used.has(`${index}:${value}`)) violations.push(`${entry.file}: 颜色例外未命中，须删除或精确校准 ${entry.selector} ${entry.property}: ${value}`)
    }
  })
  return [...new Set(violations)]
}

export function renderDesignContract() {
  return [
    '<!-- design-contracts:start -->',
    '状态与组件入口的机器事实源为 `frontend/scripts/design-contracts.json`；本段由 `npm run check:contracts:docs` 核对，禁止在段外重复定义这些列表状态。',
    '基础列表使用 `.app-interaction-list-item`，需要明确条目边界时显式叠加 `.app-interaction-list-item--outlined`；样式唯一入口为 `styles/global.css`。',
    ...Object.entries(designContracts.listTokens).map(([key, value]) => `共享变量 \`${key}\` = \`${value}\`。`),
    '',
    '| 状态 | 共享声明 |', '|---|---|',
    ...designContracts.listStates.map(state => `| ${state.name} | ${Object.entries(state.declarations).map(([key, value]) => `\`${key}: ${value}\``).join('；')}${state.forbidden?.length ? `；不得覆盖 ${state.forbidden.map(key => `\`${key}\``).join('、')}` : ''} |`),
    '',
    '基础与描边列表共同消费选中浅底、键盘焦点、禁用/加载守卫及减少动画偏好，不浮起。描边变体仅显式接入时启用，当前由方案选择器承接筛选、评分、买卖方案；角色、字典和图标候选保留基础形态。消费方通过共享扩展点表达差异，不得私写状态配方。',
    '<!-- design-contracts:end -->',
  ].join('\n')
}

export function auditDesignStateContract(css, design) {
  const violations = []
  const root = postcss.parse(css)
  for (const [property, value] of Object.entries(designContracts.listTokens)) {
    const matches = []
    root.walkDecls(property, decl => { matches.push(decl) })
    if (matches.length !== 1 || matches[0].parent.selector !== ':root' || matches[0].value !== value) {
      violations.push(`global.css: ${property} 必须由唯一根级列表契约定义`)
    }
  }
  const knownSelectors = new Set(designContracts.listStates.map(state => state.selector))
  root.walkRules(rule => {
    if (!cssClasses(rule.selector).some(name => ['app-interaction-list-item', 'app-interaction-list-item--outlined'].includes(name))) return
    rule.walkDecls(decl => {
      if (protectedProperty(designContracts.styleRoles[0], decl.prop) && !knownSelectors.has(rule.selector)) {
        violations.push(`global.css: ${rule.selector} 的 ${decl.prop} 未进入唯一列表状态契约`)
      }
    })
  })
  for (const state of designContracts.listStates) {
    const matches = []
    root.walkRules(rule => { if (rule.selector === state.selector) matches.push(rule) })
    if (matches.length !== 1) { violations.push(`global.css: ${state.name} 必须有唯一状态声明`); continue }
    if (state.media && !(matches[0].parent.type === 'atrule' && matches[0].parent.name === 'media'
      && matches[0].parent.params === state.media)) violations.push(`global.css: ${state.name} 媒体条件与契约不一致`)
    const declarations = Object.fromEntries(matches[0].nodes.filter(node => node.type === 'decl').map(node => [node.prop, node.value]))
    for (const [property, value] of Object.entries(state.declarations)) {
      if (declarations[property] !== value) violations.push(`global.css: ${state.name} ${property} 与状态契约不一致`)
    }
    for (const property of state.forbidden ?? []) if (property in declarations) violations.push(`global.css: ${state.name} 不得覆盖 ${property}`)
  }
  const block = design.match(/<!-- design-contracts:start -->[\s\S]*?<!-- design-contracts:end -->/g) ?? []
  if (block.length !== 1 || block[0] !== renderDesignContract()) violations.push('DESIGN.md: 列表状态声明与机器契约不一致')
  const rest = design.replace(/<!-- design-contracts:start -->[\s\S]*?<!-- design-contracts:end -->/g, '')
  if (rest.includes('.app-interaction-list-item')) violations.push('DESIGN.md: 列表状态只能在唯一契约区定义，段外请引用锚点')
  return violations
}

/** 无底文字命令与图标、菜单状态各由共享入口维护，防止透明化误伤状态反馈。 */
export function auditButtonStates(css) {
  const rules = []
  postcss.parse(css).walkRules(rule => { rules.push(rule) })
  const violations = []
  const declarations = rule => Object.fromEntries((rule?.nodes ?? [])
    .filter(node => node.type === 'decl').map(node => [node.prop, node.value]))
  const text = rules.filter(rule => rule.selector.includes('.el-button.is-text:not(.is-has-bg, .app-row-actions-menu__item,'))
  if (text.length !== 1 || ['--app-button-hover-bg', '--app-button-pressed-bg']
    .some(key => declarations(text[0])[key] !== 'transparent')) {
    violations.push('buttonStates.css: 普通无底文字命令悬浮/按下必须透明，并隔离显式 bg 和菜单项')
  }
  // 中性与语义文字共用按下规则；色相不取决于正文色，主题只切换加深/提亮方向。
  if (declarations(rules.find(rule => rule.selector === ':root'))['--app-button-text-state-target'] !== 'var(--el-color-black)'
    || declarations(rules.find(rule => rule.selector === "html[data-layout-mode='dark']"))['--app-button-text-state-target'] !== 'var(--el-color-white)') {
    violations.push('buttonStates.css: 文字命令状态色必须白天向黑加深、夜间向白提亮')
  }
  const textState = declarations(text[0])
  if (textState['--app-button-hover-text'] !== 'var(--app-button-tone)'
    || textState['--app-button-pressed-text'] !== 'color-mix(in srgb, var(--app-button-tone) 80%, var(--app-button-text-state-target))') {
    violations.push('buttonStates.css: 中性文字命令悬浮必须使用纯主色，按下统一增强 20%')
  }
  const semanticTextSelector = 'html[data-layout-preset] .el-button.is-text:where(.el-button--primary, .el-button--success, .el-button--warning, .el-button--danger, .is-tone-primary, .is-tone-success, .is-tone-warning, .is-tone-danger):not(.is-has-bg, .app-row-actions-menu__item, .app-interaction-target, .app-interaction-trigger, .app-interaction-choice)'
  const semanticText = rules.filter(rule => rule.selector === semanticTextSelector)
  if (semanticText.length !== 1 || declarations(semanticText[0])['--app-button-hover-text']
    !== 'color-mix(in srgb, var(--app-button-tone) 88%, var(--app-button-text-state-target))') {
    violations.push('buttonStates.css: 语义文字命令悬浮统一增强 12%，不得影响 bg、菜单或专用交互角色')
  }
  const icon = rules.filter(rule => rule.selector === 'html[data-layout-preset] .app-icon-button:not([data-close-size])')
  if (icon.length !== 1 || declarations(icon[0])['--app-button-hover-bg'] !== 'var(--app-icon-hover-bg)'
    || declarations(icon[0])['--app-button-pressed-bg'] !== 'var(--app-icon-pressed-bg)') {
    violations.push('buttonStates.css: 图标悬浮/按下须消费共享轻量反馈，关闭角色独立')
  }
  const selected = rules.find(rule => rule.selector.includes(".app-icon-button:is([aria-pressed='true'], [aria-expanded='true'], .is-open)"))
  if (declarations(selected)['--app-button-rest-bg'] !== 'var(--app-interaction-selected-background)') {
    violations.push('buttonStates.css: 图标选中/展开必须保留状态底色')
  }
  return violations
}

/** link 必须声明导航意图，避免只为透明外观把执行命令写成链接。 */
export function auditButtonKinds(sources) {
  const violations = []
  for (const { file, source } of sources) {
    const { template } = sourceParts(file, source)
    if (!template) continue
    walkTemplate(template, node => {
      if (!['el-button', 'ElButton'].includes(node.tag)) return
      const links = attributes(node, 'link')
      const texts = attributes(node, 'text')
      const kind = attributes(node, 'data-button-kind')
      const navigation = kind.some(prop => prop.type === 6 && attributeText(prop) === 'navigation')
      const rowAdapter = file === 'components/AppRowActions.vue'
        && links.length === 1 && texts.length === 1
        && links.every(prop => prop.type === 7 && attributeText(prop) === "action.kind === 'navigation'")
        && texts.every(prop => prop.type === 7 && attributeText(prop) === "action.kind !== 'navigation'")
        && kind.some(prop => prop.type === 7 && attributeText(prop) === "action.kind ?? 'command'")
      if (links.length && (links.some(prop => prop.type === 7) ? !rowAdapter : !navigation)) {
        violations.push(`${file}:${node.loc.start.line} link 必须显式声明 data-button-kind="navigation"；普通命令使用 text`)
      }
      if (navigation && (!links.length || texts.length)) {
        violations.push(`${file}:${node.loc.start.line} 导航角色须使用 link，不能混用 text`)
      }
    })
  }
  return violations
}

export function auditDesignContracts(sources = designSources(), design = readFileSync(join(frontendRoot, '../DESIGN.md'), 'utf8')) {
  return [
    ...auditComponentEntries(sources), ...auditStyleComponents(sources, undefined, undefined, { verifyRegistry: true }),
    ...auditSharedStyles(sources, designContracts.styleRoles, { verifyOwners: true }), ...auditRuntimeStyles(sources, undefined, { verifyOwners: true }), ...auditColorSources(sources),
    ...auditButtonKinds(sources),
    ...auditButtonStates(sources.find(item => item.file === 'styles/buttonStates.css')?.source ?? ''),
    ...auditDesignStateContract(sources.find(item => item.file === 'styles/global.css')?.source ?? '', design),
  ]
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const violations = process.argv.includes('--docs') ? auditDesignStateContract(
    readFileSync(join(frontendRoot, 'src/styles/global.css'), 'utf8'), readFileSync(join(frontendRoot, '../DESIGN.md'), 'utf8'),
  ) : auditDesignContracts()
  if (violations.length) { console.error(violations.join('\n')); process.exitCode = 1 }
  else console.log('共享入口、状态样式、颜色来源与列表状态文档契约检查通过。')
}
