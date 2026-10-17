import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { parse as parseVue } from 'vue/compiler-sfc'
import postcss from 'postcss'
import ts from 'typescript'

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const central = new Set(['styles/global.css', 'layout/themeSurfaces.ts', 'layout/useLayoutPreset.ts', 'layout/presets.ts'])
const surfaceProperty = /^(?:background(?:-(?:color|image))?|backgroundColor|backgroundImage|border(?:-(?:top|right|bottom|left|inline|block))?(?:-color)?|borderColor|outline(?:-color)?)$/
const knownRoles = new Set([...readFileSync(join(frontend, 'src/layout/themeSurfaces.ts'), 'utf8').matchAll(/'(--app-(?:surface|border|overlay)-[\w-]+)'/g)].map(match => match[1]))
for (const state of ['success', 'warning', 'danger']) for (const role of ['surface', 'border']) knownRoles.add(`--app-${role}-${state}`)
const rawColor = /#[\da-f]{3,8}\b|\brgba?\(|\bhsla?\(/i
// 品牌装饰仅豁免已登记的具体选择器与声明，不豁免整个登录页。
const exceptions = [
  // DESIGN §39 的明暗示意图标，以及登录页品牌轨迹；均不承担普通内容或控件表面。
  ['App.vue', '.mode-orb--light', 'background', 'radial-gradient(circle at 38% 35%, #ffffff 0 20%, #9ec5ff 22% 48%, #3b82f6 51% 100%)'],
  ['App.vue', '.mode-orb--dark', 'background', 'radial-gradient(circle at 60% 38%, #dbeafe 0 16%, #4b7bbd 18% 40%, #172554 43% 100%)'],
  ['App.vue', '.mode-orb--system', 'background', 'linear-gradient(115deg, #3b82f6 0 50%, #172554 50% 100%)'],
  ['views/LoginView.vue', '.login-brand::after', 'background', 'linear-gradient(transparent, color-mix(in srgb, var(--login-track) 48%, transparent), transparent)'],
  ['views/LoginView.vue', '.market-orbit', 'border', '1px solid color-mix(in srgb, var(--login-accent) 10%, transparent)'],
  ['views/LoginView.vue', '.market-index', 'border-left', '1px solid color-mix(in srgb, var(--login-track) 45%, transparent)'],
  ['views/LoginView.vue', '.market-readout', 'border-left', '1px solid color-mix(in srgb, var(--login-track) 52%, transparent)'],
  ['views/LoginView.vue', '.market-ticker', 'background', 'color-mix(in srgb, var(--login-panel-bg) 78%, var(--login-accent) 3%)'],
  ['views/LoginView.vue', '.login-auth', 'background', 'radial-gradient(circle at 85% 0, color-mix(in srgb, var(--login-accent) 12%, transparent), transparent 28%), var(--login-page-bg)'],
]

function sourceFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    if (entry.name === '__tests__') return []
    const path = join(directory, entry.name)
    return entry.isDirectory() ? sourceFiles(path)
      : /\.(vue|css|ts)$/.test(path) && !/\.(?:d|spec|test)\.ts$/.test(path) ? [path] : []
  })
}

/** 扫描 CSS、Vue 静态/绑定样式与脚本样式对象；只约束表面与边界，不约束金融序列身份色。 */
export function auditSurfaces(sources) {
  const violations = []
  const report = (file, line, message) => violations.push(`${file}:${line} ${message}`)
  function value(file, line, selector, property, text) {
    if (central.has(file)) return
    for (const match of text.matchAll(/var\(\s*(--app-(?:surface|border|overlay)-[\w-]+)/g)) {
      if (!knownRoles.has(match[1])) report(file, line, `未定义的表面/边界角色：${match[1]}`)
    }
    if (/^--app-(?:surface|border|overlay)-/.test(property)) {
      report(file, line, `角色只能在主题事实源定义：${property}`)
    }
    if (!surfaceProperty.test(property)
      && !(/^--/.test(property) && /(?:background|border|bg)(?:-|$)/.test(property))) return
    if (exceptions.some(([f, s, p, v]) => f === file && s === selector && p === property && v === text.replace(/\s+/g, ' ').trim())) return
    if (/color-mix\s*\(/i.test(text)) {
      report(file, line, `${selector} ${property} 不得私自混色，请消费表面/边界角色`)
    }
    if (rawColor.test(text) || /\b(?:white|black|gr[ae]y|red|blue|green|yellow|orange|purple|pink)\b/i.test(text.replace(/var\([^,()]+\)/g, ''))) {
      report(file, line, `${selector} ${property} 不得硬编码颜色或颜色兜底`)
    }
  }
  function css(file, content, offset = 0, selectorOverride) {
    try {
      postcss.parse(content).walkDecls(declaration => value(file,
        offset + (declaration.source?.start?.line ?? 1),
        selectorOverride ?? declaration.parent.selector ?? '', declaration.prop, declaration.value))
    } catch (error) { report(file, offset + 1, `样式无法解析：${error.reason ?? error.message}`) }
  }
  function script(file, content, offset = 0) {
    const ast = ts.createSourceFile(file, content, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
    function visit(node) {
      if (ts.isPropertyAssignment(node)) {
        const name = ts.isComputedPropertyName(node.name) ? node.name.expression : node.name
        const key = ts.isStringLiteralLike(name) ? name.text : name.getText(ast)
        if (ts.isStringLiteralLike(node.initializer)) {
          value(file, offset + ast.getLineAndCharacterOfPosition(node.getStart()).line + 1,
            '脚本样式', key, node.initializer.text)
        }
      }
      if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.EqualsToken
        && ts.isPropertyAccessExpression(node.left) && node.left.expression.getText(ast).endsWith('.style')
        && ts.isStringLiteralLike(node.right)) {
        value(file, offset + ast.getLineAndCharacterOfPosition(node.getStart()).line + 1,
          '脚本样式赋值', node.left.name.text, node.right.text)
      }
      if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)
        && node.expression.name.text === 'setProperty' && node.expression.expression.getText(ast).endsWith('.style')
        && node.arguments.length >= 2 && ts.isStringLiteralLike(node.arguments[0]) && ts.isStringLiteralLike(node.arguments[1])) {
        value(file, offset + ast.getLineAndCharacterOfPosition(node.getStart()).line + 1,
          '脚本样式赋值', node.arguments[0].text, node.arguments[1].text)
      }
      ts.forEachChild(node, visit)
    }
    visit(ast)
  }
  for (const { file, source } of sources) {
    if (file.endsWith('.vue')) {
      const { descriptor, errors } = parseVue(source, { filename: file })
      if (errors.length) { report(file, 1, 'Vue 文件无法解析'); continue }
      for (const block of descriptor.styles) css(file, block.content, block.loc.start.line - 1)
      for (const block of [descriptor.script, descriptor.scriptSetup].filter(Boolean)) {
        script(file, block.content, block.loc.start.line - 1)
      }
      // 模板属性由 Vue AST 读取，避免换行、引号及同名 HTML 文本造成漏检。
      function template(node) {
        if (node.type === 1) {
          for (const prop of node.props ?? []) {
            if (prop.type === 6 && prop.name === 'style' && prop.value) {
              css(file, `x { ${prop.value.content} }`, prop.loc.start.line - 1, '模板 style')
            }
            if (prop.type === 7 && prop.name === 'bind' && prop.arg?.content === 'style' && prop.exp) {
              script(file, `const style = (${prop.exp.content})`, prop.loc.start.line - 1)
            }
          }
        }
        for (const child of node.children ?? []) template(child)
      }
      if (descriptor.template?.ast) template(descriptor.template.ast)
    } else if (file.endsWith('.css')) css(file, source)
    else script(file, source)
  }
  return { files: sources.length, violations: [...new Set(violations)] }
}

export function auditSurfaceTree(root = join(frontend, 'src')) {
  return auditSurfaces(sourceFiles(root).map(path => ({
    file: relative(root, path), source: readFileSync(path, 'utf8'),
  })))
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  const result = auditSurfaceTree()
  if (result.violations.length) {
    process.stderr.write(result.violations.join('\n') + '\n')
    process.exitCode = 1
  } else process.stdout.write(`表面与边界契约校验通过：${result.files} 个源码文件。\n`)
}
