import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { parse as parseVue } from 'vue/compiler-sfc'
import { baseParse } from '@vue/compiler-dom'
import postcss from 'postcss'

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const rows = new Set(['AppControlRow', 'AppTabToolbar', 'AppAdvancedSearch', 'StockChartPanelHeader'])
// 共享组合组件的具名插槽在消费方仍须接受同一门禁。
const rowSlots = new Map([['AppWorkspacePane', ['actions', 'toolbar', 'footer']], ['AppDetailSection', 'actions'],
  ['MarketAnalysisHeader', 'controls'], ['AppDetailDrawer', 'header-actions']])
const boundaries = new Set(['AppForm', 'AppDialog', 'PageDrawer', 'PageDrawerSurface',
  'AppDataTable', 'AppRowActions', 'AppCloseButton'])
const controls = new Set(['el-button', 'el-input', 'el-input-number', 'el-date-picker',
  'el-radio-group', 'el-radio-button', 'el-checkbox-group', 'el-checkbox-button', 'el-segmented',
  'AppSelect', 'AppFilterSelect', 'AppMultiSelect', 'AppSearchInput', 'AppDatePicker',
  'TradeDatePicker', 'PageSegmented', 'AppIconButton', 'AssetProfileSelect',
  'MarketBenchmarkSelect', 'IndicatorSelect', 'KlineRangeSelect', 'StockCodeMultiSelect',
  'StockGroupSelect', 'BoardGroupSelect'])
const shared = new Set(['components/AppControlRow.vue', 'components/AppTabToolbar.vue',
  'components/AppAdvancedSearch.vue', 'components/AppSelect.vue', 'components/AppFilterSelect.vue',
  'components/PageSegmented.vue', 'components/AppIconButton.vue'])
const height = /^(?:(?:min-|max-)?(?:height|block-size)|--app-control-row-height)$/
const classNames = source => [...source.matchAll(/\.([\w-]+)/g)].map(match => match[1])
const staticAttr = (node, name) => node.props.find(p => p.type === 6 && p.name === name)

/** 行级消费检查与构建共享；例外按附属角色、表单/浮层边界区分，不按整页放行。 */
export function auditControlRows(sources) {
  const violations = []
  for (const { file, source } of sources) {
    const report = (line, message) => violations.push(`${file}:${line} ${message}`)
    const rowClasses = new Set(['app-control-row', 'app-tab-toolbar', 'app-advanced-search'])
    const controlClasses = new Set()
    const descriptor = file.endsWith('.vue') ? parseVue(source).descriptor : undefined
    const template = descriptor?.template
    function inspect(node, inRow = false) {
      if (node.type !== 1) return
      if (boundaries.has(node.tag)) inRow = false
      const ownsRow = rows.has(node.tag) || node.props.some(p =>
        p.type === 7 && p.name === 'bind' && p.arg?.content === 'data-control-row')
      inRow ||= ownsRow
      const classes = (staticAttr(node, 'class')?.value?.content ?? '').split(/\s+/).filter(Boolean)
      if (ownsRow) classes.forEach(c => rowClasses.add(c))
      const textCommand = staticAttr(node, 'text') || staticAttr(node, 'link')
      const participant = inRow && controls.has(node.tag) && !textCommand
      if (participant || ownsRow) {
        if (participant) classes.forEach(c => controlClasses.add(c))
        const line = template.loc.start.line + node.loc.start.line - 1
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
        inspect(child, inRow || !!slotOwnsRow)
      })
    }
    if (template) baseParse(template.content).children.forEach(node => inspect(node))
    const styles = descriptor?.styles ?? (file.endsWith('.css') ? [{ content: source }] : [])
    for (const style of styles) {
      if (shared.has(file) || file === 'styles/global.css') continue
      postcss.parse(style.content).walkRules(rule => {
        const classes = classNames(rule.selector)
        const rowRule = classes.some(c => rowClasses.has(c))
        const controlRule = classes.some(c => controlClasses.has(c))
          || rowRule && /\.(?:el-(?:input|select|button|segmented)|page-segmented|seg-btn)\b/.test(rule.selector)
        if (!rowRule && !controlRule) return
        rule.walkDecls(decl => {
          if (!height.test(decl.prop)) return
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
  } else console.log('操作行共同尺寸检查通过')
}
