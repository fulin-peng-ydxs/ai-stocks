import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import postcss from 'postcss'
import ts from 'typescript'
import {
  attributeText, attributes, auditComponentEntries, designContracts, designSources,
  frontendRoot, literalStrings, scriptAst, sourceParts, walkScript, walkTemplate,
} from './design-source.mjs'

const classesOf = node => attributes(node, 'class').flatMap(prop => {
  if (prop.type === 6) return attributeText(prop).split(/\s+/)
  const ast = scriptAst('class.ts', `(${attributeText(prop)})`)
  return literalStrings(ast).flatMap(value => value.split(/\s+/))
}).filter(Boolean)
const cssClasses = selector => [...selector.matchAll(/\.([_a-zA-Z][\w-]*)/g)].map(match => match[1])
const staticClassesOf = node => attributes(node, 'class').filter(prop => prop.type === 6)
  .flatMap(prop => attributeText(prop).split(/\s+/))

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
      const root = [node, ...ancestors].find(item => classesOf(item).includes(role.className))
      if (root && (root === node || role.descendants)) targets.push({ node, role, classes,
        exclusions: [...staticClassesOf(node), ...(root === node ? [role.className] : [])],
        ancestors: ancestors.flatMap(classesOf) })
    }
  })
  return targets
}

function protectedProperty(role, property) {
  return role.properties.includes(property)
    || role.properties.includes('background') && property.startsWith('background-')
    || role.properties.includes('border') && /^border-(?:top|right|bottom|left)(?:-(?:color|width|style))?$/.test(property)
}

/** 使用选择器中的角色/别名及后代关系判断覆盖，不剥离伪类后再靠 DOM 偶然匹配。 */
function targetsSelector(selector, target) {
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
  // 明确排除该角色的普通名称样式不属于覆盖；排除条件不能含组合器或其它状态。
  for (const match of subject.matchAll(/:not\(([^()]+)\)/g)) {
    if (nestingDepth(subject.slice(0, match.index)) > 0) continue
    if (match[1].split(',').some(value => target.exclusions.includes(value.trim().match(/^\.([\w-]+)$/)?.[1]))) return false
  }
  const classes = cssClasses(subject)
  if (classes.some(name => target.classes.includes(name))) return true
  const tag = subject.match(/^[a-z][\w-]*/i)?.[0]
  return tag === target.node.tag && (!cssClasses(selector).length
    || cssClasses(selector).some(name => target.ancestors.includes(name)))
}

export function auditSharedStyles(sources, roles = designContracts.styleRoles) {
  const violations = []
  const prepared = sources.map(item => ({ ...item, ...sourceParts(item.file, item.source) }))
  const externalTargets = prepared.flatMap(item => roleTargets(item.template, roles))
  for (const item of prepared) {
    if (item.file === 'styles/global.css') continue
    const targets = (item.file.endsWith('.css') ? externalTargets : roleTargets(item.template, roles))
      .filter(target => roles.some(role => role.className === target.role.className))
    const report = (selector, property) => violations.push(`${item.file}: ${selector} 不得私设 ${property}；使用共享角色入口`)
    for (const style of item.styles) postcss.parse(style.content).walkRules(rule => {
      for (const target of targets) {
        if (!rule.selectors.some(selector => targetsSelector(selector, target))) continue
        rule.walkDecls(decl => {
          if (protectedProperty(target.role, decl.prop)) report(rule.selector, decl.prop)
        })
      }
    })
    for (const target of targets) {
      for (const prop of attributes(target.node, 'style')) {
        if (prop.type === 6) postcss.parse(`x{${attributeText(prop)}}`).walkDecls(decl => {
          if (protectedProperty(target.role, decl.prop)) report('<inline style>', decl.prop)
        })
        else {
          const expression = attributeText(prop)
          if (!expression.trim().startsWith('{')) {
            report('<dynamic style>', '不可静态确认的样式绑定')
            continue
          }
          const ast = scriptAst(item.file, `(${expression})`)
          walkScript(ast, node => {
            if (ts.isPropertyAssignment(node)) {
              const key = node.name.getText(ast).replace(/['"]/g, '').replace(/[A-Z]/g, c => `-${c.toLowerCase()}`)
              if (protectedProperty(target.role, key)) report('<dynamic style>', key)
            }
            if (ts.isSpreadAssignment(node)) report('<dynamic style>', '展开样式')
          })
        }
      }
      if (target.node.props.some(prop => prop.type === 7 && prop.name === 'bind' && !prop.arg)) {
        report('<v-bind>', '整包属性绑定')
      }
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

export function auditDesignContracts(sources = designSources(), design = readFileSync(join(frontendRoot, '../DESIGN.md'), 'utf8')) {
  return [
    ...auditComponentEntries(sources), ...auditSharedStyles(sources), ...auditColorSources(sources),
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
