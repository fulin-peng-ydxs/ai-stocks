import { dirname, posix, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { baseParse } from '@vue/compiler-dom'
import postcss from 'postcss'
import ts from 'typescript'
import { attributeText, attributes, designSources, scriptAst, sourceParts, walkScript, walkTemplate } from './design-source.mjs'
import { expressionContext, UNKNOWN } from './design-expressions.mjs'

const canonical = value => value.replaceAll('-', '').toLowerCase()
const propName = node => ts.isComputedPropertyName(node) ? node.expression.getText().replace(/['"]/g, '') : node.getText().replace(/['"]/g, '')

/** 有限布尔表达式展开，用于证明 if/else、&&、|| 和枚举条件互斥；未知表达式按原子处理。 */
function conditionAlternatives(expression, negate = false) {
  const node = typeof expression === 'string' ? scriptAst('condition.ts', `(${expression})`).statements[0].expression : expression
  if (ts.isParenthesizedExpression(node)) return conditionAlternatives(node.expression, negate)
  if (ts.isPrefixUnaryExpression(node) && node.operator === ts.SyntaxKind.ExclamationToken) return conditionAlternatives(node.operand, !negate)
  if (node.kind === ts.SyntaxKind.TrueKeyword || node.kind === ts.SyntaxKind.FalseKeyword) return (node.kind === ts.SyntaxKind.TrueKeyword) !== negate ? [[]] : []
  if (ts.isBinaryExpression(node)) {
    const op = node.operatorToken.kind
    if ([ts.SyntaxKind.AmpersandAmpersandToken, ts.SyntaxKind.BarBarToken].includes(op)) {
      const left = conditionAlternatives(node.left, negate), right = conditionAlternatives(node.right, negate)
      const and = (op === ts.SyntaxKind.AmpersandAmpersandToken) !== negate
      if (!and) return [...left, ...right]
      if (left.length * right.length > 128) return [[{ key: node.getText(), value: !negate }]]
      return left.flatMap(a => right.map(b => [...a, ...b]))
    }
    const literal = value => ts.isStringLiteralLike(value) ? `string:${value.text}`
      : ts.isNumericLiteral(value) ? `number:${value.text}`
        : value.kind === ts.SyntaxKind.TrueKeyword ? 'boolean:true'
          : value.kind === ts.SyntaxKind.FalseKeyword ? 'boolean:false' : undefined
    if ([ts.SyntaxKind.EqualsEqualsEqualsToken, ts.SyntaxKind.ExclamationEqualsEqualsToken].includes(op)) {
      const reversed = literal(node.left) != null
      const value = literal(reversed ? node.left : node.right)
      if (value != null) return [[{key:(reversed ? node.right : node.left).getText().replace(/\s/g,''),value,equal:(op === ts.SyntaxKind.EqualsEqualsEqualsToken) !== negate}]]
    }
  }
  return [[{ key: node.getText().replace(/\s/g, ''), value: !negate }]]
}

function mutuallyExclusive(conditions) {
  let choices = [[]]
  for (const condition of conditions) {
    const alternatives = conditionAlternatives(condition)
    if (choices.length * alternatives.length > 256) return false
    choices = choices.flatMap(choice => alternatives.map(alternative => [...choice, ...alternative])).filter(choice => !choice.some((a, index) => choice.slice(index + 1).some(b =>
      a.key === b.key && (typeof a.value === 'boolean' && typeof b.value === 'boolean' ? a.value !== b.value
        : a.equal && b.equal ? a.value !== b.value : a.equal !== b.equal && a.value === b.value))))
    if (!choices.length) return true
  }
  return false
}

const contexts = new WeakMap()
function contextFor(source) {
  if (!contexts.has(source)) contexts.set(source, expressionContext(source.file, source.source))
  return contexts.get(source)
}

/** 模板值按输出求值；条件只展开真实 computed，不以函数内同名变量或属性名替换。 */
function bindings(context) {
  const strings = text => context.values(context.parse(text)).filter(value => typeof value === 'string')
  const condition = text => {
    const ast = scriptAst('condition.ts', `(${text})`)
    const seen = new Set()
    const result = ts.transform(ast.statements[0].expression, [transform => {
      const visit = node => {
        if (ts.isStringLiteralLike(node)) return ts.factory.createStringLiteral(node.text)
        if (ts.isNumericLiteral(node)) return ts.factory.createNumericLiteral(node.text)
        if (ts.isPropertyAccessExpression(node)) {
          const reference = context.unwrap(node.expression).node
          if (node.name.text === 'value' && reference && (ts.isCallExpression(reference) && context.vueCall(reference) || ts.isIdentifier(reference) && !context.declaration(reference))) return ts.visitNode(node.expression, visit)
          if (node.expression.getText() === 'props') return node.name
          return ts.visitEachChild(node, visit, transform)
        }
        if (ts.isIdentifier(node) && !(ts.isPropertyAccessExpression(node.parent) && node.parent.name === node)) {
          const value = context.unwrap(node).node
          if (value && !seen.has(value) && ts.isCallExpression(value) && context.vueCall(value) === 'computed') {
            const callback = value.arguments[0]
            if (callback && ts.isArrowFunction(callback) && !ts.isBlock(callback.body)) {
              seen.add(value)
              return ts.factory.createParenthesizedExpression(ts.visitNode(callback.body, visit))
            }
          }
        }
        return ts.visitEachChild(node, visit, transform)
      }
      return root => ts.visitNode(root, visit)
    }])
    try { return ts.createPrinter().printNode(ts.EmitHint.Expression, result.transformed[0], ast) }
    finally { result.dispose() }
  }
  const primary = text => {
    const resolveValue = (input, env = new Map(), seen = new Set()) => {
      const resolved = context.unwrap(input, env), node = resolved.node
      env = resolved.env
      if (!node || seen.has(node)) return 'false'
      seen = new Set([...seen,node])
      if (ts.isStringLiteralLike(node)) return node.text === 'primary' ? 'true' : 'false'
      if (ts.isConditionalExpression(node)) return `((${node.condition.getText()}) && (${resolveValue(node.whenTrue,env,seen)})) || (!(${node.condition.getText()}) && (${resolveValue(node.whenFalse,env,seen)}))`
      if (ts.isCallExpression(node) && context.vueCall(node) === 'computed') {
        const callback = node.arguments[0]
        if (callback && ts.isArrowFunction(callback) && !ts.isBlock(callback.body)) return resolveValue(callback.body,env,seen)
      }
      return context.values(node,env).includes('primary') ? 'true' : 'false'
    }
    return resolveValue(context.parse(text))
  }
  return { ...context, strings, condition, primary }
}

/** 普通标题、共享标题属性/插槽及其有限字符串绑定；帮助正文不属于标题文本。 */
export function auditHeadings(sources) {
  const violations = []
  for (const item of sources) {
    const { file, source } = item
    const { template, strings, tag, props, line } = bindings(contextFor(item))
    const check = (text, line) => { if (/[()（）]/.test(text)) violations.push(`${file}:${contextFor(item).line(line)} 标题不得含圆括号；说明使用 HelpHint / HelpTip`) }
    const read = node => {
      if (node.type === 2) check(node.content, node.loc.start.line)
      if (node.type === 5) strings(node.content.content).forEach(text => check(text, node.loc.start.line))
      if (node.type === 1 && !['helphint','helptip','helptipitem','apphoverinfo'].includes(tag(node))
        && !attributes(node, 'class').some(prop => /(?:^|\s)(?:sub|meta|[\w-]+__(?:meta|subtitle))(?:\s|$)/.test(attributeText(prop)))) node.children.forEach(read)
    }
    walkTemplate(template, (node, ancestors) => {
      const role = attributes(node, 'role').some(prop => attributeText(prop) === 'heading')
      const classes = attributes(node, 'class').flatMap(prop => prop.type === 6 ? [attributeText(prop)] : strings(attributeText(prop))).join(' ')
      const choice = ancestors.some(parent => /^(?:elradio|eloption|elcheckbox)$/.test(tag(parent)))
      if (/^h[1-6]$/.test(node.tag) || role || !choice && /(?:^|\s)(?:title|[\w-]+(?:__|-)(?:title|heading))(?:\s|$)/.test(classes)) node.children.forEach(read)
      // 原生 title 是提示或 iframe 名称，只有组件的 title 才承担标题角色。
      // 图表共享标题把动态括注归入 HelpHint，真实组件行为由消费者契约测试守卫。
      if (tag(node) !== 'stockchartpanelheader' && (!/^[a-z]+$/.test(node.tag) || node.tag.includes('-'))) {
        for (const value of props(node)) if (typeof value.title === 'string') check(value.title, node.loc.start.line)
      }
      if (node.tag === 'template' && node.props.some(prop => prop.type === 7 && prop.name === 'slot' && /^(?:header|title)$/.test(prop.arg?.content ?? ''))) node.children.forEach(read)
    })
  }
  return [...new Set(violations)]
}

// 仅已登记的技术几何/非交互循环可保留原值；登记不能成为文件级豁免。
export const consistencyExceptions = [
  { file: 'views/LoginView.vue', selector: '.market-track-line', property: 'animation', value: 'track-flow 18s linear infinite', reason: '登录品牌行情轨迹循环，不属于交互状态过渡' },
  { file: 'views/LoginView.vue', selector: '.market-ticker-track', property: 'animation', value: 'ticker-scroll 34s linear infinite', reason: '品牌行情带匀速循环，保持内容可读速度' },
  { file: 'views/LoginView.vue', selector: '.login-field input:-webkit-autofill,\n.login-field input:-webkit-autofill:hover,\n.login-field input:-webkit-autofill:focus,\n.login-field input:-webkit-autofill:active', property: 'transition', value: 'background-color 9999s ease-out 0s', reason: '浏览器自动填充底色兼容，非用户可见交互动效' },
]

/** CSS、内联对象与 HTML 字符串共同检查；普通数值配置不作为 CSS 处理。 */
export function auditSpacingMotion(sources, exceptions = consistencyExceptions, { verifyExceptions = false } = {}) {
  const violations = [], used = new Set(), roots = new Map(), scoped = new Map()
  const motionOwners = new Map([
    ...['--app-motion-content','--app-motion-page','--app-motion-collapse','--app-motion-spin','--app-motion-ease'].map(name => [name,'styles/global.css']),
    ...['--app-scrollbar-show-duration','--app-scrollbar-hide-duration'].map(name => [name,'styles/scrollbar.css']),
  ])
  const trees = sources.flatMap(item => sourceParts(item.file,item.source).styles.map(style => ({...item,style,tree:postcss.parse(style.content)})))
  const scopeKey = (file, rule) => {
    const path = []
    for (let node = rule; node; node = node.parent) if (node.type === 'rule' || node.type === 'atrule') path.unshift(node.type === 'rule' ? node.selector : `@${node.name} ${node.params}`)
    return `${file}:${path.join(' / ')}`
  }
  for (const {file,tree} of trees) tree.walkDecls(decl => {
    if (decl.prop.startsWith('--')) {
      const key = scopeKey(file,decl.parent), entries = scoped.get(key) ?? new Map()
      entries.set(decl.prop,decl.value); scoped.set(key,entries)
    }
    if (decl.prop.startsWith('--') && decl.parent.selector === ':root') roots.set(decl.prop,decl.value)
    if (motionOwners.has(decl.prop) && motionOwners.get(decl.prop) !== file) violations.push(`${file}:${decl.source.start.line} ${decl.prop} 只能由共享 token 所有者定义`)
  })
  // 只读取当前声明作用域及根定义；不同选择器中的同名私有变量不能混成一个值。
  const variables = (file,parent) => {
    const result = new Map(roots), chain = []
    for (let scope = parent; scope; scope = scope.parent) chain.unshift(scope)
    for (const scope of chain) for (const [key,value] of scoped.get(scopeKey(file,scope)) ?? []) result.set(key,value)
    return result
  }
  const expand = (value, definitions, motion, seen = new Set()) => {
    // 平衡括号，保留嵌套 var()/calc() 的 fallback。
    let result = ''
    for (let index = 0; index < value.length;) {
      if (value.slice(index,index+4) !== 'var(') {result += value[index++];continue}
      let end = index+4, depth = 1, comma = -1
      for (; end < value.length && depth; end++) {
        if (value[end] === '(') depth++
        if (value[end] === ')') depth--
        if (value[end] === ',' && depth === 1 && comma < 0) comma = end
      }
      if (depth) return result + value.slice(index)
      const name = value.slice(index+4,comma < 0 ? end-1 : comma).trim()
      const fallback = comma < 0 ? '' : value.slice(comma+1,end-1)
      const replacement = definitions.get(name) ?? fallback
      result += motion && motionOwners.has(name) || seen.has(name) || !replacement
        ? value.slice(index,end) : expand(replacement,definitions,motion,new Set([...seen,name]))
      index = end
    }
    return result
  }
  const inspect = (file, selector, property, value, line, definitions = roots) => {
    property = property === property.toUpperCase() ? property.toLowerCase() : property.replace(/[A-Z]/g,char => `-${char.toLowerCase()}`).toLowerCase()
    const spacing = /^(?:gap|row-gap|column-gap|padding(?:-.+)?|margin(?:-.+)?)$/.test(property)
    const motion = /^(?:transition|animation)(?:-.+)?$/.test(property)
    if (!spacing && !motion) return
    const effective = expand(String(value),definitions,motion)
    const oddSpacing = spacing && [...effective.matchAll(/(?:^|[^\w.])(-?(?:\d*\.)?\d+)px\b/gi)].some(match => [5,7,9,11,13,15].includes(Math.abs(Number(match[1]))))
    const privateMotion = motion && [...effective.matchAll(/(?:\d*\.)?\d+(?:ms|s)\b/gi)].some(match => parseFloat(match[0]) !== 0)
    const easingValue = effective.replace(/var\([^)]*\)/g,'')
    const privateEasing = motion && /\b(?:ease(?:-in-out|-in|-out)?|cubic-bezier|steps)\b/i.test(easingValue)
      || property.startsWith('transition') && /\blinear\b/i.test(easingValue)
    if (!oddSpacing && !privateMotion && !privateEasing) return
    const index = exceptions.findIndex(item => item.file === file && item.selector === selector && item.property === property && item.value === value && item.reason?.trim())
    if (index >= 0) {used.add(index);return}
    violations.push(`${file}:${line} ${selector} ${property}: ${value} ${oddSpacing ? '间距含禁止的游离刻度' : '动效时长须消费共享 token'}`)
  }
  for (const {file,style,tree} of trees) tree.walkDecls(decl => inspect(file,decl.parent.selector ?? '',decl.prop,decl.value,(style.loc?.start.line ?? 1)-1+decl.source.start.line,variables(file,decl.parent)))
  for (const item of sources) {
    const {file} = item, ctx = contextFor(item)
    const cssObject = value => {
      if (value === UNKNOWN || value == null) return {}
      if (Array.isArray(value)) return Object.assign({},...value.map(cssObject))
      if (typeof value === 'object') return value
      if (typeof value !== 'string') return {}
      const result = {}
      postcss.parse(`x{${value}}`).walkDecls(decl => {result[decl.prop] = decl.value})
      return result
    }
    const inspectValue = (value, line) => {
      const object = cssObject(value), definitions = new Map([...roots,...Object.entries(object).filter(([key]) => key.startsWith('--'))])
      for (const [key,value] of Object.entries(object)) {
        if (motionOwners.has(key) && motionOwners.get(key) !== file) violations.push(`${file}:${line} ${key} 只能由共享 token 所有者定义`)
        if (value !== UNKNOWN) inspect(file,'<style object>',key,typeof value === 'number' ? `${value}px` : String(value),line,definitions)
      }
    }
    walkTemplate(ctx.template,node => {
      for (const props of ctx.props(node)) if ('style' in props) inspectValue(props.style,ctx.line(node.loc.start.line))
    })
    walkScript(ctx.ast,node => {
      // 仅真正 HTML style 属性和 CSS 文本出口；业务说明中的 CSS 示例不属于消费。
      const candidate = ts.isStringLiteralLike(node) || ts.isTemplateExpression(node) || ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken
      if (!candidate) return
      const line = ctx.ast.getLineAndCharacterOfPosition(node.getStart()).line+1
      for (const value of ctx.values(node)) if (typeof value === 'string') {
        for (const match of value.matchAll(/\bstyle\s*=\s*(["'])(.*?)\1/gs)) inspectValue(match[2],line)
        if (ts.isVariableDeclaration(node.parent) && /(?:_CSS|CssText)$/.test(node.parent.name.getText())
          || ts.isPropertyAssignment(node.parent) && propName(node.parent.name) === 'extraCssText') inspectValue(value,line)
      }
    })
  }
  if (verifyExceptions) exceptions.forEach((item,index) => {
    if (!used.has(index)) violations.push(`${item.file}: 间距/动效例外已失效或缺少依据: ${item.selector} ${item.property}`)
  })
  return [...new Set(violations)]
}

/** 按分支和独立弹层判断；循环不能豁免页面其它动作，plain/text/link 不计为实色。 */
export function auditPrimaryActions(sources) {
  const violations = []
  for (const item of sources) {
    const { file } = item
    const { template, tag, strings, condition, primary, props, line } = bindings(contextFor(item))
    const actions = [], ast = baseParse(template)
    function walk(parent, context = ast, conditions = []) {
      let preceding = []
      for (const node of parent.children ?? []) {
        if (node.type !== 1) continue
        const directive = name => node.props.find(prop => prop.type === 7 && prop.name === name)
        let branch = [...conditions]
        if (directive('if')) { preceding = [directive('if').exp?.content ?? 'true']; branch.push(...preceding) }
        else if (directive('else-if') || directive('else')) {
          branch.push(...preceding.map(value => `!(${value})`))
          if (directive('else-if')) { const value = directive('else-if').exp.content; preceding.push(value); branch.push(value) }
        } else preceding = []
        if (directive('show')) branch.push(directive('show').exp.content)
        const independent = /^(?:appdialog|pagedrawer|appdetaildrawer|eltabpane)$/.test(tag(node))
        const scope = independent ? node : context
        const solid = props(node).some(value => value.type === 'primary'
          && !['plain','text','link'].some(key => value[key] !== UNKNOWN && !!value[key]))
        if (/^(?:elbutton|appiconbutton)$/.test(tag(node)) && solid) {
          const actionBranch = [...branch]
          for (const name of ['plain','text','link']) {
            const prop = [...node.props].reverse().find(prop => prop.type === 6 && prop.name === name || prop.type === 7 && prop.name === 'bind' && (!prop.arg || prop.arg.content === name))
            if (prop?.type === 7 && prop.arg) actionBranch.push(`!(${attributeText(prop)})`)
          }
          const lastType = [...node.props].reverse().find(prop => prop.type === 6 && prop.name === 'type'
            || prop.type === 7 && prop.name === 'bind' && (!prop.arg || prop.arg.content === 'type'))
          if (lastType?.type === 7 && lastType.arg) actionBranch.push(primary(attributeText(lastType)))
          actions.push({ node, scope, branch:actionBranch })
        }
        walk(node, scope, branch)
      }
    }
    walk(ast)
    // 条件只做可确定的互斥证明；复杂业务条件仍需组件测试/页面验收。
    for (let index = 0; index < actions.length; index++) for (const second of actions.slice(index + 1)) {
      const first = actions[index]
      if (first.scope === second.scope && !mutuallyExclusive([...first.branch, ...second.branch].map(value => condition(value)))) violations.push(`${file}:${line(first.node.loc.start.line)},${line(second.node.loc.start.line)} 同一操作上下文存在多个实色 primary 主按钮`)
    }
  }
  return violations
}

const timestampField = /(?:^|[._])(?:[a-zA-Z]+_at|timestamp|datetime|dateTime|ts)$/
const formatterNames = new Set(['formatDateTimeSeconds','formatDateTimeMinutes','formatDateOnly','formatClockTime','formatClockMinutes','formatDateYear'])
/** 对每个可见输出分支追踪真实导入与局部包装器；不把数组操作或计算载荷当成日期展示。 */
export function auditDateTimeConsumers(sources) {
  const violations = []
  const byFile = new Map(sources.map(item => [item.file,item]))
  const importTarget = (info,context) => {
    if (!info) return null
    const path = info.module.startsWith('@/') ? info.module.slice(2) : info.module.startsWith('.') ? posix.normalize(posix.join(dirname(context.file),info.module)) : ''
    const source = byFile.get(path) ?? byFile.get(`${path}.ts`)
    if (!source) return null
    const imported = contextFor(source), fn = imported.globals.get(info.name)
    return fn && ts.isFunctionDeclaration(fn) && fn.body ? {context:imported,fn} : null
  }
  const functionOutputs = fn => {
    const outputs = []
    const walk = node => {
      if (node !== fn.body && ts.isFunctionLike(node)) return
      if (ts.isReturnStatement(node) && node.expression) outputs.push(node.expression)
      ts.forEachChild(node,walk)
    }
    walk(fn.body)
    return outputs
  }
  const trustedCall = (call,env,context,seen = new Set()) => {
    const info = context.origin(call.expression,env)
    if (!info) return false
    const path = info.module.startsWith('@/') ? info.module.slice(2) : info.module.startsWith('.') ? posix.normalize(posix.join(dirname(context.file),info.module)) : ''
    if (path.replace(/\.ts$/, '') === 'utils/dateTime') return formatterNames.has(info.name)
    const source = byFile.get(path) ?? byFile.get(`${path}.ts`)
    if (!source || seen.has(source.file+':'+info.name)) return false
    const imported = contextFor(source), fn = imported.globals.get(info.name)
    if (!fn || !ts.isFunctionDeclaration(fn) || !fn.body) return false
    seen = new Set([...seen,source.file+':'+info.name])
    const outputs = functionOutputs(fn)
    const safe = node => {
      node = imported.unwrap(node).node
      if (ts.isStringLiteralLike(node)) return true
      if (ts.isConditionalExpression(node)) return safe(node.whenTrue) && safe(node.whenFalse)
      return ts.isCallExpression(node) && trustedCall(node,new Map(),imported,seen)
    }
    return outputs.length > 0 && outputs.every(safe)
  }
  const inspector = ctx => {
    const trusted = (call,env) => trustedCall(call,env,ctx)
    const dateValue = (input,env = new Map(),hint = false,seen = new Set()) => {
      const resolved = ctx.unwrap(input,env), node = resolved.node
      if (!node || seen.has(node)) return false
      seen = new Set([...seen,node]);env=resolved.env
      if (ts.isParameter(node)) return !node.type || !ts.isArrayTypeNode(node.type) ? hint || /date|time|stamp|(?:^|_)ts$/i.test(node.name.getText()) : false
      if (ts.isIdentifier(node) || ts.isPropertyAccessExpression(node)) {
        const text = node.getText().replace(/\?\./g,'.')
        return timestampField.test(text) || /(?:^|[._])(?:date|trade_date|time)$/.test(text)
      }
      if (ts.isStringLiteralLike(node)) return /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(node.text)
      if (ts.isNewExpression(node) && /^(?:Date|Intl\.DateTimeFormat)$/.test(node.expression.getText())) return true
      if (ts.isCallExpression(node)) {
        if (trusted(node,env)) return false
        if (ts.isPropertyAccessExpression(node.expression)) return dateValue(node.expression.expression,env,hint,seen)
        return ctx.returns(node,env).some(entry => dateValue(entry.node,entry.env,hint,seen))
      }
      return false
    }
    const unsafe = (input,env = new Map(),hint = false,seen = new Set()) => {
      const resolved = ctx.unwrap(input,env), node = resolved.node
      if (!node || seen.has(node)) return false
      seen = new Set([...seen,node]);env=resolved.env
      const read = child => unsafe(child,env,hint,seen)
      if (ts.isConditionalExpression(node)) return read(node.whenTrue) || read(node.whenFalse)
      if (ts.isTemplateExpression(node)) return node.templateSpans.some(span => read(span.expression))
      if (ts.isBinaryExpression(node)) {
        // 日期仅用于条件、时间差或边界计算时，不构成日期展示。
        if (node.operatorToken.kind === ts.SyntaxKind.PlusToken || node.operatorToken.kind === ts.SyntaxKind.QuestionQuestionToken || node.operatorToken.kind === ts.SyntaxKind.BarBarToken) return read(node.left) || read(node.right)
        return false
      }
      if (ts.isCallExpression(node)) {
        if (trusted(node,env)) return false
        const vue = ctx.vueCall(node)
        if (vue === 'computed') {
          const callback = node.arguments[0]
          if (callback && ts.isArrowFunction(callback) && !ts.isBlock(callback.body)) return read(callback.body)
        } else if (vue && node.arguments[0]) return read(node.arguments[0])
        const results = ctx.returns(node,env)
        if (results.length) return results.some(entry => unsafe(entry.node,entry.env,hint,seen))
        const imported = importTarget(ctx.origin(node.expression,env),ctx)
        if (imported && node.arguments.some(arg => dateValue(arg,env,hint))) {
          const analysis = inspector(imported.context)
          return functionOutputs(imported.fn).some(output => analysis.unsafe(output,new Map(),true,seen))
        }
        const name = node.expression.getText()
        if (/^(?:Date\.parse|Number|Boolean)$/.test(name)) return false
        if (name === 'String') return node.arguments.some(read)
        if (ts.isPropertyAccessExpression(node.expression)) {
          const method = node.expression.name.text, receiver = node.expression.expression
          if (/^(?:slice|substring|substr|replace|replaceAll|split|toISOString|toLocaleString|toLocaleTimeString|toLocaleDateString|format)$/.test(method)
            && dateValue(receiver,env,hint)) return true
          if (read(receiver)) return true
        }
        // 未知格式化函数不能靠 fmt/format 命名放行。
        return /(?:format|fmt|date|time)/i.test(name) && node.arguments.some(arg => dateValue(arg,env,hint))
      }
      return dateValue(node,env,hint)
    }
    return {unsafe}
  }
  for (const item of sources) {
    const {file} = item
    if (file === 'utils/dateTime.ts') continue
    const ctx = contextFor(item)
    const {unsafe} = inspector(ctx)
    const report = (node,line,hint = false) => {
      if (unsafe(node,new Map(),hint)) violations.push(`${file}:${line} 日期时间展示须消费 utils/dateTime.ts: ${node.getText().trim()}`)
    }
    walkTemplate(ctx.template,node => {
      for (const child of node.children) if (child.type === 5) report(ctx.parse(child.content.content),ctx.line(child.loc.start.line))
      for (const prop of node.props) {
        if (prop.type !== 7 || !prop.exp) continue
        if (['text','html'].includes(prop.name) || prop.name === 'bind' && /^(?:label|description|title|content|text|formatter)$/.test(prop.arg?.content ?? '')) report(ctx.parse(prop.exp.content),ctx.line(prop.loc.start.line))
      }
      if (ctx.tag(node) === 'apptablecolumn' && !node.children.some(child => child.type === 1) && !attributes(node,'formatter').length) {
        for (const props of ctx.props(node)) if (typeof props.prop === 'string' && timestampField.test(props.prop)) violations.push(`${file}:${ctx.line(node.loc.start.line)} 日期时间列须提供共享 formatter 或展示插槽: ${props.prop}`)
      }
    })
    walkScript(ctx.ast,node => {
      const line = ctx.ast.getLineAndCharacterOfPosition(node.getStart()).line+1
      if (ts.isFunctionDeclaration(node) || ts.isArrowFunction(node) || ts.isFunctionExpression(node)) {
        const name = node.name?.getText() ?? (ts.isVariableDeclaration(node.parent) ? node.parent.name.getText() : '')
        if (!/^(?:fmt(?:Time|Date)|format(?:Date|Time|Timestamp)|date$|ymd$)/i.test(name) || !node.body) return
        const walk = body => {
          if (body !== node.body && ts.isFunctionLike(body)) return
          if (ts.isReturnStatement(body) && body.expression) report(body.expression,line,true)
          ts.forEachChild(body,walk)
        }
        if (ts.isBlock(node.body)) walk(node.body)
        else report(node.body,line,true)
      }
      // 文案出口；普通载荷字段与 Date.parse 的计算链不参与。
      if (ts.isVariableDeclaration(node) && node.initializer && /(?:label|title|description|content|html|tooltip)$/i.test(node.name.getText())) report(node.initializer,line)
      if (ts.isPropertyAssignment(node) && /^(?:label|title|description|content|text|html|tooltip|formatter)$/.test(propName(node.name))) report(node.initializer,line)
    })
  }
  return [...new Set(violations)]
}

/** 重复配方是复用候选，需按语义判断；不将相似外观机械升级为硬违规。 */
export function findStyleReuseCandidates(sources) {
  const recipes = new Map()
  for (const { file, source } of sources) for (const style of sourceParts(file, source).styles) {
    postcss.parse(style.content).walkRules(rule => {
      const declarations = rule.nodes.filter(node => node.type === 'decl')
      if (declarations.length < 3 || !declarations.some(decl => /var\(--/.test(decl.value))) return
      const signature = declarations.map(decl => `${decl.prop}:${decl.value}${decl.important ? '!important' : ''}`).sort().join(';')
      const entries = recipes.get(signature) ?? []
      entries.push({ file, selector: rule.selector, line: rule.source.start.line })
      recipes.set(signature, entries)
    })
  }
  return [...recipes.values()].filter(entries => entries.length > 1)
}

/** 已发布的数字强调角色不得复制配方；其余相似样式只输出候选，保留语义判断。 */
export function auditSharedStyleRecipes(sources) {
  const global = sources.find(item => item.file === 'styles/global.css')
  if (!global) return []
  let recipe = []
  postcss.parse(global.source).walkRules(rule => {
    if (rule.selector === '.app-data-emphasis') recipe = rule.nodes.filter(node => node.type === 'decl').map(decl => [decl.prop, decl.value])
  })
  if (!recipe.length) return ['styles/global.css: 缺少 app-data-emphasis 共享配方']
  const violations = []
  for (const { file, source } of sources) {
    if (file === 'styles/global.css') continue
    for (const style of sourceParts(file, source).styles) postcss.parse(style.content).walkRules(rule => {
      if (recipe.every(([property, value]) => rule.nodes.some(node => node.type === 'decl' && node.prop === property && node.value === value))) violations.push(`${file}:${rule.source.start.line} ${rule.selector} 复制数字强调配方；消费 app-data-emphasis`)
    })
  }
  return violations
}

export function auditDesignConsistency(sources, options = {}) {
  return [...auditHeadings(sources), ...auditSpacingMotion(sources, consistencyExceptions, options), ...auditPrimaryActions(sources), ...auditDateTimeConsumers(sources), ...auditSharedStyleRecipes(sources)]
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const sources = designSources()
  if (process.argv.includes('--reuse-candidates')) console.log(JSON.stringify(findStyleReuseCandidates(sources), null, 2))
  else {
    const violations = auditDesignConsistency(sources, { verifyExceptions: true })
    if (violations.length) { console.error(violations.join('\n')); process.exitCode = 1 }
    else console.log('标题、间距、动效、主按钮及日期时间消费检查通过。')
  }
}
