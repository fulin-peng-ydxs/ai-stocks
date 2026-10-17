import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { parse as parseVue } from 'vue/compiler-sfc'
import postcss from 'postcss'
import ts from 'typescript'

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const fontProperties = new Set(['font', 'font-size', 'font-weight', 'font-family', 'line-height'])
const scriptProperties = new Set([...fontProperties, 'fontSize', 'fontWeight', 'fontFamily', 'lineHeight'])
// 例外收窄到选择器、属性和当前值；不能豁免整个品牌或登录文件。
const exceptions = [
  ['components/BrandMark.vue', '.brand-mark__word-main', 'font-size', '27px'],
  ['components/BrandMark.vue', '.brand-mark__word-main', 'font-weight', '800'],
  ['views/LoginView.vue', '.mr-value', 'font-size', 'clamp(24px, 1.9cqw, 30px)'],
  ['views/LoginView.vue', '.login-brand-copy h1', 'font-size', 'clamp(42px, 4.5cqw, 70px)'],
  ['views/LoginView.vue', '.login-brand-copy h1', 'line-height', '1.18'],
  ['views/LoginView.vue', '.login-brand-copy h1', 'font-family', "'Songti SC', STSong, 'SimSun', serif"],
  ['views/LoginView.vue', '.login-card-title h2', 'font-size', '29px'],
  ['views/LoginView.vue', '.login-card-title h2', 'font-family', "'Songti SC', STSong, 'SimSun', serif"],
]

function sourceFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    if (entry.name === '__tests__') return []
    const path = join(dir, entry.name)
    if (entry.isDirectory()) return sourceFiles(path)
    return /\.(vue|css|ts)$/.test(path) && !/\.(d|spec|test)\.ts$/.test(path) ? [path] : []
  })
}

/** AST 扫描 CSS、Vue 模板绑定及 TS 对象/HTML 样式；同时支持小夹具验证漏检边界。 */
export function auditTypography(sources) {
  const definitions = new Map()
  const declarations = []
  const scriptReferences = []
  const violations = []
  const report = (file, line, message) => violations.push(`${file}:${line} ${message}`)
  const varNames = value => [...value.matchAll(/var\(\s*(--[\w-]+)/g)].map(match => match[1])

  function css(file, content, offset = 0, selectorOverride) {
    try {
      postcss.parse(content).walkDecls(declaration => {
        const selector = selectorOverride ?? declaration.parent.selector ?? ''
        const line = offset + (declaration.source?.start?.line ?? 1)
        if (declaration.prop.startsWith('--')) {
          const values = definitions.get(declaration.prop) ?? []
          values.push(declaration.value)
          definitions.set(declaration.prop, values)
          if (/font|line-height/.test(declaration.prop)
            && file !== 'styles/global.css'
            && !(file === 'components/PageDrawerSurface.vue' && declaration.prop === '--app-settings-group-level-one-font-size')) {
            report(file, line, `字体变量必须在共享事实源定义: ${declaration.prop}`)
          }
        }
        if (fontProperties.has(declaration.prop) || /^--.*(?:font|line-height)/.test(declaration.prop)) {
          declarations.push({ file, selector, line, prop: declaration.prop, value: declaration.value })
          if (declaration.prop === 'font-size' && declaration.value === 'var(--app-font-size-data)') {
            for (const [prop, value] of [['font-weight', 'var(--app-font-weight-section)'], ['line-height', 'var(--app-line-height-data)']]) {
              if (!declaration.parent.nodes.some(node => node.prop === prop && node.value === value)) {
                report(file, line, `${selector} 数字强调必须完整消费字号、字重和行高角色`)
              }
            }
          }
        }
      })
    } catch (error) { report(file, offset + 1, `CSS 无法解析: ${error.reason ?? error.message}`) }
  }

  function script(file, content, offset = 0) {
    const ast = ts.createSourceFile(file + '.ts', content, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
    if (ast.parseDiagnostics.length) report(file, offset + 1, '脚本无法解析')
    const propertyName = name => ts.isComputedPropertyName(name) && ts.isStringLiteralLike(name.expression)
      ? name.expression.text : name.getText(ast).replace(/['"]/g, '')
    const visit = node => {
      const line = offset + ast.getLineAndCharacterOfPosition(node.getStart(ast)).line + 1
      if (ts.isCallExpression(node) && ['numberToken', 'chartCssVariable'].includes(node.expression.getText(ast))
        && node.arguments[0] && ts.isStringLiteralLike(node.arguments[0])
        && /^--app-(?:font|line-height)/.test(node.arguments[0].text)) {
        scriptReferences.push({ file, line, name: node.arguments[0].text })
      }
      if (ts.isShorthandPropertyAssignment(node) && scriptProperties.has(node.name.text)) {
        report(file, line, '字体对象不能使用私有简写属性')
      }
      if (ts.isVariableDeclaration(node) && node.name.getText(ast) === 'typography'
        && node.initializer?.getText(ast) !== 'chartTypography()') {
        report(file, line, '图表字体快照必须来自 chartTypography()')
      }
      if (ts.isPropertyAssignment(node) && scriptProperties.has(propertyName(node.name))) {
        const value = node.initializer.getText(ast)
        // 数字转换和 ECharts 消费集中在共享适配器；普通模板绑定也由此检测。
        const sharedFamily = file === 'components/chartTheme.ts' && node.name.getText(ast) === 'fontFamily'
          && value === "chartCssVariable('--app-font-family-base', 'system-ui, sans-serif')"
        if (!sharedFamily && !/^(?:\w+\.)*typography\.(?:fontFamily|axis|compact|body|annotationLineHeight|regular|section|strong)$/.test(value)) {
          report(file, line, `内联字体必须迁入共享样式或图表适配器: ${node.name.getText(ast)}: ${value}`)
        }
      }
      if (ts.isPropertyAssignment(node) && propertyName(node.name) === 'typography'
        && node.initializer.getText(ast) !== 'chartTypography()') {
        report(file, line, '图表字体快照必须来自 chartTypography()')
      }
      if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.EqualsToken
        && ts.isPropertyAccessExpression(node.left) && scriptProperties.has(node.left.name.text)) {
        report(file, line, '禁止通过脚本单独写入字体样式')
      }
      // HTML tooltip 字符串同样校验，模板插值不会成为原始字号的豁免入口。
      if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)
        || ts.isTemplateHead(node) || ts.isTemplateMiddle(node) || ts.isTemplateTail(node)) {
        const text = node.text
        for (const match of text.matchAll(/(?:^|[;"'])\s*(font(?:-size|-weight|-family)?|line-height)\s*:\s*([^;"'<>]*)/g)) {
          const value = match[2].trim()
          if (!value || /\$\{$/.test(value)) {
            report(file, line, 'HTML 字体样式不能由私有插值生成')
          } else declarations.push({ file, line, selector: '<script style>', prop: match[1], value })
        }
      }
      ts.forEachChild(node, visit)
    }
    visit(ast)
  }

  for (const { file, source } of sources) {
    if (file.endsWith('.css')) css(file, source)
    else if (file.endsWith('.vue')) {
      const { descriptor, errors } = parseVue(source, { filename: file })
      if (errors.length) report(file, 1, 'Vue 无法解析')
      descriptor.styles.forEach(block => css(file, block.content, block.loc.start.line - 1))
      for (const block of [descriptor.script, descriptor.scriptSetup].filter(Boolean)) {
        script(file, block.content, block.loc.start.line - 1)
      }
      const walkTemplate = node => {
        for (const prop of node.props ?? []) {
          if (prop.type === 6 && fontProperties.has(prop.name)) {
            report(file, prop.loc.start.line, '字体呈现属性必须迁入共享样式')
          }
          if (prop.type === 6 && prop.name === 'style') css(file, `x {${prop.value?.content ?? ''}}`, prop.loc.start.line - 1, '<template style>')
          if (prop.type === 7 && prop.name === 'bind' && prop.exp) {
            script(file, `(${prop.exp.content})`, prop.loc.start.line - 1)
          }
        }
        node.children?.forEach(walkTemplate)
      }
      if (descriptor.template?.ast) walkTemplate(descriptor.template.ast)
    } else script(file, source)
  }

  for (const { file, line, name } of scriptReferences) {
    if (!definitions.has(name)) report(file, line, `未定义变量: ${name}`)
  }
  const roots = {
    'font-size': /^--(?:app-font-size-|app-icon-|app-state-icon-size|app-nav-icon-size|app-button-icon-size)/,
    'font-weight': /^--app-font-weight-/,
    'font-family': /^--app-font-family-/,
    'line-height': /^--app-line-height-/,
  }
  function belongsToRole(name, property, seen = new Set()) {
    if (seen.has(name) || !definitions.has(name)) return false
    const rootToken = roots[property]?.test(name)
    seen.add(name)
    return definitions.get(name).every(value => {
      const refs = varNames(value)
      return refs.length > 0
        ? tokenExpression(value) && refs.every(ref => belongsToRole(ref, property, new Set(seen)))
        : rootToken === true
    })
  }
  // 普通声明只允许完整 var 表达式；唯一数值运算是浮层跟随根显示比例。
  function tokenExpression(raw) {
    const value = raw.replace(/!important\s*$/, '').trim()
    if (/^calc\(\s*var\(--app-(?:font-size|line-height)-[\w-]+\)\s*\*\s*var\(--app-display-scale,\s*1\)\s*\)$/.test(value)) return true
    const start = value.match(/^var\(\s*--[\w-]+/)
    if (!start || !value.endsWith(')')) return false
    let depth = 1
    let comma = -1
    for (let index = start[0].length; index < value.length; index++) {
      if (value[index] === '(') depth++
      if (value[index] === ')') depth--
      if (!depth && index !== value.length - 1) return false
      if (value[index] === ',' && depth === 1) comma = index
    }
    if (depth !== 0) return false
    return comma === -1
      ? value.slice(start[0].length, -1).trim() === ''
      : value.slice(start[0].length, comma).trim() === '' && tokenExpression(value.slice(comma + 1, -1))
  }
  for (const declaration of declarations) {
    const { file, selector, line, prop, value } = declaration
    const refs = varNames(value)
    for (const name of refs) {
      if (!definitions.has(name)) report(file, line, `未定义变量: ${name}`)
    }
    if (prop.startsWith('--')) continue
    if (exceptions.some(rule => rule.join('|') === [file, selector, prop, value].join('|'))) continue
    if (value === 'inherit') continue
    if (prop === 'font') {
      report(file, line, `font 简写只允许 inherit: ${value}`)
      continue
    }
    if (!refs.length || !tokenExpression(value)
      || refs.some(name => name !== '--app-display-scale' && !belongsToRole(name, prop))
      || refs.every(name => name === '--app-display-scale')) {
      report(file, line, `${selector} ${prop} 未消费有效字体角色: ${value}`)
    }
  }
  return { files: sources.length, declarations: declarations.length, violations: [...new Set(violations)] }
}

export function auditTypographyTree(root = join(frontend, 'src')) {
  const sources = sourceFiles(root).map(path => ({ file: relative(root, path), source: readFileSync(path, 'utf8') }))
  const result = auditTypography(sources)
  const design = readFileSync(join(root, '../../DESIGN.md'), 'utf8')
  const documented = new Set([...design.matchAll(/`(--app-(?:font|line-height)[\w-]*)`/g)].map(match => match[1]))
  const globalCss = sources.find(source => source.file === 'styles/global.css')?.source ?? ''
  for (const match of globalCss.matchAll(/(--app-(?:font|line-height)[\w-]*)\s*:/g)) {
    if (!documented.has(match[1])) result.violations.push(`DESIGN.md: 字体 token 未登记角色: ${match[1]}`)
  }
  return result
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const result = auditTypographyTree()
  if (result.violations.length) {
    console.error(result.violations.join('\n'))
    process.exitCode = 1
  } else console.log(`字体规范校验通过：${result.files} 个源码文件，${result.declarations} 条声明；无未定义变量或游离字体规则。`)
}
