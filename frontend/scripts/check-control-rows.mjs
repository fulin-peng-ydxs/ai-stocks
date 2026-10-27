import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { parse as parseVue } from 'vue/compiler-sfc'
import { baseParse } from '@vue/compiler-dom'
import postcss from 'postcss'
import ts from 'typescript'
import { scriptAst, walkScript } from './design-source.mjs'

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const rows = new Set(['AppControlRow', 'AppTabToolbar', 'AppAdvancedSearch', 'StockChartPanelHeader'])
// 共享组合组件的具名插槽在消费方仍须接受同一门禁。
const rowSlots = new Map([['AppWorkspacePane', ['actions', 'toolbar', 'footer']], ['AppDetailSection', 'actions'],
  ['MarketAnalysisHeader', 'controls'], ['AppDetailDrawer', 'header-actions'], ['TradeDirectionGroupGrid', 'actions']])
const boundaries = new Set(['AppForm', 'AppDialog', 'PageDrawer', 'PageDrawerSurface',
  'AppDataTable', 'AppRowActions', 'AppCloseButton'])
const controls = new Set(['el-button', 'el-input', 'el-input-number', 'el-date-picker',
  'el-radio-group', 'el-radio-button', 'el-checkbox-group', 'el-checkbox-button', 'el-segmented',
  'AppSelect', 'AppFilterSelect', 'AppMultiSelect', 'AppSearchInput', 'AppDatePicker',
  'TradeDatePicker', 'PageSegmented', 'AppIconButton', 'AssetProfileSelect',
  'IconPicker', 'MarketBenchmarkSelect', 'IndicatorSelect', 'IndicatorParamFields', 'KlineRangeSelect', 'StockCodeMultiSelect',
  'StockGroupSelect', 'BoardGroupSelect'])
const shared = new Set(['components/AppControlRow.vue', 'components/AppTabToolbar.vue',
  'components/AppAdvancedSearch.vue', 'components/AppSelect.vue', 'components/AppFilterSelect.vue',
  'components/PageSegmented.vue', 'components/AppIconButton.vue', 'components/IconPicker.vue'])
// 基础适配器仅透传自身尺寸 API；业务消费方仍须通过所属表单/操作组声明层级。
const sizeAdapters = new Set([...shared, 'components/AppRowActions.vue', 'components/AppSearchInput.vue',
  'components/indicator/IndicatorParamFields.vue'])
const compactRoles = new Set(['AppDataTable', 'AppTableColumn', 'el-table', 'el-table-column',
  'AppRowActions', 'AppStateBlock', 'AppStatusNotice'])
const height = /^(?:(?:min-|max-)?(?:height|block-size)|--app-control-row-height)$/
const segmentedGeometry = /^(?:(?:min-|max-)?(?:width|height|inline-size|block-size)|display|flex(?:-.+)?|grid(?:-.+)?|padding(?:-.+)?|font(?:-.+)?|border(?:-.+)?|background(?:-.+)?|gap|row-gap|column-gap|line-height|color|box-shadow|--.+)$/
const fieldBoundaries = new Set(['AppDataTable', 'AppTableColumn', 'el-table', 'el-table-column',
  'AppRowActions', 'AppStateBlock', 'AppStatusNotice', 'AppDialog', 'PageDrawer', 'PageDrawerSurface'])
const classNames = source => [...source.matchAll(/\.([\w-]+)/g)].map(match => match[1])
const staticAttr = (node, name) => node.props.find(p => p.type === 6 && p.name === name)
const inputControls = new Set([...controls].filter(tag => !['el-button', 'AppIconButton'].includes(tag)))
inputControls.add('el-switch')
const sharedSpacingClasses = new Set(['app-cluster-sm', 'app-cluster-md', 'app-cluster-lg',
  'app-stack-sm', 'app-stack-md', 'app-stack-lg'])
const horizontalMargin = /^(?:margin-(?:left|right|inline(?:-start|-end)?)|margin(?:Left|Right|Inline(?:Start|End)?))$/

/** 只计算可同时出现的直接控件；template 不提供布局，互斥分支取最大值。 */
function simultaneousInputs(children) {
  const elements = children.filter(node => node.type === 1)
  const count = node => node.tag === 'template'
    ? node.props.some(prop => prop.type === 7 && prop.name === 'slot') ? 0 : simultaneousInputs(node.children)
    : inputControls.has(node.tag) ? 1 : 0
  let total = 0
  for (let index = 0; index < elements.length; index++) {
    const node = elements[index]
    let amount = count(node)
    if (node.props.some(prop => prop.type === 7 && prop.name === 'if')) {
      while (elements[index + 1]?.props.some(prop => prop.type === 7 && ['else-if', 'else'].includes(prop.name))) {
        amount = Math.max(amount, count(elements[++index]))
      }
    }
    total += amount
  }
  return total
}

function compensatesSpacing(property, value) {
  const parts = postcss.list.space(value.replace(/!important\s*$/, '').trim())
  const nonZero = part => !/^(?:auto|0(?:px|rem|em|%)?)$/.test(part)
  if (property === 'margin') return parts.length === 1 && nonZero(parts[0])
    || parts.length > 1 && nonZero(parts[1])
    || parts.length === 4 && nonZero(parts[3])
  return horizontalMargin.test(property) && parts.some(nonZero)
}

/** 与构建共用控件尺寸和分段几何门禁；紧凑例外按表格/附属动作角色识别，不按页面放行。 */
export function auditControlRows(sources) {
  const violations = []
  for (const { file, source } of sources) {
    const report = (line, message) => violations.push(`${file}:${line} ${message}`)
    const rowClasses = new Set(['app-control-row', 'app-tab-toolbar', 'app-advanced-search'])
    const controlClasses = new Set()
    const fieldControlClasses = new Set()
    let hasFieldInputs = false
    const segmentedClasses = new Set(['page-segmented', 'seg-btn', 'seg-label', 'seg-indicator'])
    const descriptor = file.endsWith('.vue') ? parseVue(source).descriptor : undefined
    const template = descriptor?.template
    const styles = descriptor?.styles ?? (file.endsWith('.css') ? [{ content: source }] : [])
    // 日期起止范围已使用完整三列网格；必须同时存在轨道和有效 token gap，margin 不能冒充布局。
    const spacedGrids = new Set()
    for (const style of styles) postcss.parse(style.content).walkRules(rule => {
      if (!/^\.[\w-]+$/.test(rule.selector)) return
      const declarations = new Map(rule.nodes.filter(node => node.type === 'decl').map(node => [node.prop, node.value]))
      if (declarations.get('display') === 'grid' && declarations.has('grid-template-columns')
        && /^var\(--[\w-]+\)$/.test(declarations.get('gap') ?? '')) spacedGrids.add(rule.selector.slice(1))
    })
    function inspect(node, inRow = false, inField = false, compactRole = false, inFormItem = false) {
      if (node.type !== 1) return
      if (boundaries.has(node.tag)) { inRow = false; compactRole = false }
      compactRole ||= compactRoles.has(node.tag)
      if (fieldBoundaries.has(node.tag)) inField = false
      if (fieldBoundaries.has(node.tag)) inFormItem = false
      inFormItem ||= node.tag === 'el-form-item'
      if (['AppForm', 'PageSettingItem'].includes(node.tag)) inField = true
      const ownsRow = rows.has(node.tag) || node.props.some(p =>
        p.type === 7 && p.name === 'bind' && p.arg?.content === 'data-control-row')
      inRow ||= ownsRow
      const classes = (staticAttr(node, 'class')?.value?.content ?? '').split(/\s+/).filter(Boolean)
      if (ownsRow) classes.forEach(c => rowClasses.add(c))
      if ((inFormItem || inRow) && inputControls.has(node.tag)) {
        hasFieldInputs = true
        classes.forEach(c => fieldControlClasses.add(c))
        for (const prop of node.props) {
          const line = template.loc.start.line + prop.loc.start.line - 1
          if (prop.type === 6 && prop.name === 'style') {
            postcss.parse(`x{${prop.value?.content ?? ''}}`).walkDecls(decl => {
              if (compensatesSpacing(decl.prop, decl.value)) report(line, '控件不得通过私有水平 margin 补间距；使用共享容器 gap')
            })
          }
          if (prop.type === 7 && prop.name === 'bind' && prop.arg?.content === 'style' && prop.exp) {
            walkScript(scriptAst(file, `(${prop.exp.content})`), expression => {
              if (!ts.isPropertyAssignment(expression)) return
              const key = ts.isComputedPropertyName(expression.name) ? expression.name.expression : expression.name
              const name = ts.isStringLiteralLike(key) ? key.text : key.getText()
              if (name === 'margin' || horizontalMargin.test(name)) {
                const value = expression.initializer
                if (!ts.isStringLiteralLike(value) && value.getText() !== '0'
                  || ts.isStringLiteralLike(value) && compensatesSpacing(name, value.text)) {
                  report(line, '控件不得通过动态水平 margin 补间距；使用共享容器 gap')
                }
              }
            })
          }
        }
      }
      const textCommand = staticAttr(node, 'text') || staticAttr(node, 'link')
      const line = template.loc.start.line + node.loc.start.line - 1
      if (inFormItem && node.tag !== 'template' && !inputControls.has(node.tag) && !ownsRow
        && !classes.some(c => sharedSpacingClasses.has(c) || spacedGrids.has(c))
        && simultaneousInputs(node.children) > 1) {
        report(line, '同一表单项的并列输入控件必须由 AppControlRow / 共享间距容器承接；template 和私有 margin 不提供间距')
      }
      if ((inField || !compactRole && !sizeAdapters.has(file)) && !inRow && controls.has(node.tag) && node.tag !== 'AppIconButton' && !textCommand) {
        const size = node.props.find(p => p.type === 6 && p.name === 'size'
          || p.type === 7 && p.name === 'bind' && p.arg?.content === 'size')
        if (size && !(size.type === 6 && size.value?.content === 'default')) {
          report(line, '常规控件不得独立设置 size；尺寸由所属表单或操作组统一提供（含行外入口）')
        }
      }
      if (node.tag === 'PageSegmented' && file !== 'components/PageSegmented.vue') {
        classes.forEach(c => segmentedClasses.add(c))
        for (const prop of node.props) {
          if (prop.type === 6 && prop.name === 'style') {
            postcss.parse(`x{${prop.value?.content ?? ''}}`).walkDecls(decl => {
              if (segmentedGeometry.test(decl.prop)) report(line, `分段控件不得内联覆盖 ${decl.prop}；宽度由共享 fill 声明`)
            })
          }
          if (prop.type === 7 && prop.name === 'bind' && (!prop.arg || ['style', 'class'].includes(prop.arg.content))) {
            report(line, '分段控件不得通过动态样式/类或整包绑定绕过共享几何；排列使用外层容器')
          }
        }
      }
      const participant = inRow && controls.has(node.tag) && !textCommand
      if (participant || ownsRow) {
        if (participant) classes.forEach(c => controlClasses.add(c))
        if (participant && node.props.some(p => p.type === 6 && p.name === 'size'
          || p.type === 7 && p.name === 'bind' && p.arg?.content === 'size')) {
          report(line, '行内常规控件不得独立设置 size；共同尺寸由行提供')
        }
        for (const prop of node.props) {
          if (participant && prop.type === 7 && prop.name === 'bind' && !prop.arg) {
            report(line, '行内控件不得通过整包绑定绕过共同尺寸检查')
          }
          if (prop.type === 6 && prop.name === 'style') {
            postcss.parse(`x{${prop.value?.content ?? ''}}`).walkDecls(decl => {
              if (height.test(decl.prop)) report(line, `行内控件不得内联覆盖 ${decl.prop}`)
            })
          }
          if (prop.type === 7 && prop.name === 'bind' && prop.arg?.content === 'style') {
            const expression = prop.exp?.content ?? ''
            // 作用域拥有者在公共入口消费 helper，不开放业务样式豁免。
            if (ownsRow && expression === 'row.style.value'
              && (shared.has(file) || file === 'components/stock-chart/StockChartPanelHeader.vue')) continue
            if (/\b(?:height|minHeight|maxHeight|blockSize)\b|--app-control-row-height/.test(expression)
              || !expression.trim().startsWith('{')) {
              report(line, '行内控件动态样式须可确认不覆盖高度')
            }
          }
        }
      }
      node.children.forEach(child => {
        const slot = child.type === 1 && child.props.find(p => p.type === 7 && p.name === 'slot')
        const ownedSlots = rowSlots.get(node.tag)
        const slotOwnsRow = slot && (Array.isArray(ownedSlots)
          ? ownedSlots.includes(slot.arg?.content) : slot.arg?.content === ownedSlots)
        inspect(child, inRow || !!slotOwnsRow, inField && !['actions', 'header-actions', 'tail'].includes(slot?.arg?.content), compactRole, inFormItem)
      })
    }
    if (template) baseParse(template.content).children.forEach(node => inspect(node))
    for (const style of styles) {
      if (file === 'components/PageSegmented.vue') continue
      postcss.parse(style.content).walkRules(rule => {
        const classes = classNames(rule.selector)
        if (!shared.has(file) && file !== 'styles/global.css'
          && (classes.some(c => fieldControlClasses.has(c))
            || hasFieldInputs && /\.el-(?:input(?:-number)?|select|switch|date-editor)\b/.test(rule.selector))) {
          rule.walkDecls(decl => {
            if (compensatesSpacing(decl.prop, decl.value)) {
              report((style.loc?.start.line ?? 1) + (decl.source?.start?.line ?? 1) - 1,
                `控件不得通过私有水平 margin 补间距（${rule.selector}）；使用共享容器 gap`)
            }
          })
        }
        const segmentedRule = classes.some(c => segmentedClasses.has(c))
        const segmentedInternal = classes.some(c => ['seg-btn', 'seg-label', 'seg-indicator'].includes(c))
        const rowRule = classes.some(c => rowClasses.has(c))
        // 共享行默认靠左排列；Grid 隐式列会按内容收缩，必须显式声明轨道。
        const gridRow = rule.selector.split(',').some(selector => {
          const target = selector.trim().match(/(?:^|[>+~\s])((?:\.[\w-]+)+)$/)?.[1]
          return target && classNames(target).some(c => rowClasses.has(c))
        })
        if (gridRow && rule.nodes.some(node => node.type === 'decl'
          && node.prop === 'display' && ['grid', 'inline-grid'].includes(node.value))
          && !rule.nodes.some(node => node.type === 'decl'
            && ['grid', 'grid-template', 'grid-template-columns'].includes(node.prop))) {
          report((style.loc?.start.line ?? 1) + (rule.source?.start?.line ?? 1) - 1,
            `Grid 操作行必须显式声明列轨道，避免默认靠左排列造成隐式列收缩（${rule.selector}）`)
        }
        const controlRule = classes.some(c => controlClasses.has(c))
          || rowRule && /\.(?:el-(?:input|select|button|segmented)|page-segmented|seg-btn)\b/.test(rule.selector)
        if (!rowRule && !controlRule && !segmentedRule) return
        rule.walkDecls(decl => {
          if (segmentedRule && (segmentedInternal || segmentedGeometry.test(decl.prop))) {
            report((style.loc?.start.line ?? 1) + (decl.source?.start?.line ?? 1) - 1,
              `分段控件不得私自覆盖 ${decl.prop}（${rule.selector}）；使用共享尺寸及 fill`)
            return
          }
          if (shared.has(file) || file === 'styles/global.css' || !height.test(decl.prop)) return
          if (rowRule && !controlRule && decl.prop === 'min-height'
            && decl.value === 'var(--app-control-row-height)') return
          report((style.loc?.start.line ?? 1) + (decl.source?.start?.line ?? 1) - 1,
            `操作行或参与控件不得私自覆盖 ${decl.prop}（${rule.selector}）`)
        })
      })
    }
  }
  return violations
}

export function auditControlRowsTree(root = join(frontend, 'src')) {
  function files(dir) {
    return readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
      if (entry.name === '__tests__') return []
      const path = join(dir, entry.name)
      return entry.isDirectory() ? files(path) : /\.(vue|css)$/.test(path) ? [path] : []
    })
  }
  return auditControlRows(files(root).map(path => ({
    file: relative(root, path).replaceAll('\\', '/'), source: readFileSync(path, 'utf8'),
  })))
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const violations = auditControlRowsTree()
  if (violations.length) {
    console.error(violations.join('\n'))
    process.exitCode = 1
  } else console.log('控件共同尺寸与分段宽度检查通过')
}
