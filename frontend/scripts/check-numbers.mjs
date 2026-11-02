import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'
import { baseParse } from '@vue/compiler-dom'
import { designSources, sourceParts, scriptAst, walkScript, walkTemplate, attributes } from './design-source.mjs'

// 仅登记具体的非展示计算表达式，不豁免整文件。业务精度例外应放领域定义。
const calculations = new Map([
  ['views/ConfigView.vue', new Set(['(1 - w * (n - 1)).toFixed(2)', 'v.toFixed(4)', 'each.toFixed(4)', '((it.weight / otherSum) * remain).toFixed(4)'])],
  ['components/marketCompareChart.ts', new Set(['(rawMin - padding).toFixed(4)', '(rawMax + padding).toFixed(4)'])],
  ['components/stock-chart/intradayOptions.ts', new Set(['(preClose - padded).toFixed(4)', '(preClose + padded).toFixed(4)', '(padded / 2).toFixed(6)'])],
  ['components/stock-chart/StockChartWorkspace.vue', new Set(['value.toFixed(6)'])],
  ['components/stock-chart/workspaceOptions.ts', new Set(['(percentage * safeScale).toFixed(3)'])],
])

// 只识别语义明确的数量字段；日期、代码、版本、序号不通过名称猜测格式。
const countField = /^(?:count|total|length|n_trades|n_rounds|n_signals|n_positions|total_signals|hold_days|max_hold_days|window_days|actual_trade_days|missing_days|partial_days|complete_days|peak_positions|max_positions|sample_\d+|\w+_count|\w+Count|memberTotal|collectionTotal|typeTotal)$/

/** 只沿最终输出分支检查，跳过条件和函数参数，避免把计算或共享 helper 误判为直出。 */
function hasRawCount(expression) {
  const ast = scriptAst('display.ts', `(${expression})`)
  const visit = node => {
    if (ts.isPropertyAccessExpression(node)) return countField.test(node.name.text)
    if (ts.isIdentifier(node)) return countField.test(node.text)
    if (ts.isCallExpression(node)) return false
    if (ts.isPrefixUnaryExpression(node) && node.operator === ts.SyntaxKind.ExclamationToken) return false
    if (ts.isConditionalExpression(node)) return visit(node.whenTrue) || visit(node.whenFalse)
    if (ts.isBinaryExpression(node)) {
      // 比较和布尔结果不是数量文本。
      if ([ts.SyntaxKind.GreaterThanToken, ts.SyntaxKind.GreaterThanEqualsToken,
        ts.SyntaxKind.LessThanToken, ts.SyntaxKind.LessThanEqualsToken,
        ts.SyntaxKind.EqualsEqualsToken, ts.SyntaxKind.ExclamationEqualsToken,
        ts.SyntaxKind.EqualsEqualsEqualsToken, ts.SyntaxKind.ExclamationEqualsEqualsToken].includes(node.operatorToken.kind)) return false
      return visit(node.left) || visit(node.right)
    }
    let found = false
    ts.forEachChild(node, child => { if (visit(child)) found = true })
    return found
  }
  return visit(ast)
}

function auditRenderedNumbers(template, report) {
  const walk = node => {
    if (node.type === 5 && hasRawCount(node.content.content)) {
      report(`数量文本必须消费共享数值入口：${node.content.content}`)
    }
    if (node.type === 1) {
      const texts = (node.children ?? []).filter(child => child.type === 5).map(child => child.content.content).join(' ')
      if (/\b(?:pct|formatReturn|formatMarketPercent|formatPercentPoints|formatPercentPointsDetail)\s*\(/.test(texts)) {
        const staticClass = attributes(node, 'class').filter(prop => prop.type === 6).map(prop => prop.value?.content ?? '').join(' ')
        const dynamicClass = attributes(node, 'class').filter(prop => prop.type === 7).map(prop => prop.exp?.content ?? '').join(' ')
        if (/(?:^|\s)(?:up|down)(?:\s|$)/.test(staticClass) || /[<>]=?\s*0\b/.test(dynamicClass)) {
          report('金融数值判色必须消费共享入口，舍入为零时不得使用涨跌色')
        }
      }
      for (const prop of node.props) {
        if (prop.type !== 7 || prop.name !== 'bind' || !prop.exp) continue
        const name = prop.arg?.content
        // 输入控件的 value/model-value 属于编辑值；仅检查只读展示属性。
        if (['content', 'description', 'subtitle', 'meta'].includes(name)
          || name === 'value' && node.tag === 'AppDetailField') {
          if (hasRawCount(prop.exp.content)) report(`数量展示属性必须消费共享数值入口：${prop.exp.content}`)
        }
      }
      if (node.tag === 'AppTableColumn') {
        const prop = attributes(node, 'prop').find(item => item.type === 6)?.value?.content
        const hasDefault = (node.children ?? []).some(child => child.type === 1 && child.props.some(item => item.type === 7 && item.name === 'slot' && item.arg?.content === 'default'))
        if (prop && countField.test(prop) && !hasDefault && !attributes(node, 'formatter').length) {
          report('数量表格列必须声明共享格式化，不依赖原值回显')
        }
      }
    }
    for (const child of node.children ?? []) walk(child)
  }
  walk(baseParse(template))
}

/** 展示舍入必须使用共享入口；模板一律禁止，计算例外只放行精确表达式。 */
export function auditNumbers(sources) {
  const violations = []
  for (const { file, source } of sources) {
    const { scripts, template } = sourceParts(file, source)
    const report = message => violations.push(`${file}: ${message}`)
    auditRenderedNumbers(template, report)
    if (/\.(?:toFixed|toLocaleString|toPrecision)\s*\(|Intl\.NumberFormat/.test(template)) report('模板数值展示必须消费共享格式化入口')
    for (const script of scripts) {
      const ast = scriptAst(file, script)
      walkScript(ast, node => {
        if ((ts.isCallExpression(node) || ts.isNewExpression(node)) && node.expression) {
          const method = ts.isPropertyAccessExpression(node.expression) ? node.expression.name.text : ''
          if (method === 'toFixed' && !calculations.get(file)?.has(node.getText(ast))) report('禁止私有 toFixed 展示舍入')
          if (method === 'toLocaleString' || method === 'toPrecision' || node.expression.getText(ast) === 'Intl.NumberFormat') report('禁止私有数值本地化；使用 numberFormat/money/marketValue')
        }
        if (file !== 'utils/numberFormat.ts' && file !== 'utils/money.ts' && file !== 'utils/fixedDecimal.ts'
          && ts.isRegularExpressionLiteral(node) && node.text.includes('(?=(\\d{3})')) report('千分位分组只能由共享入口持有')
      })
    }
    walkTemplate(template, node => {
      if (['el-input-number', 'ElInputNumber'].includes(node.tag) && attributes(node, 'precision').length) {
        report('输入精度须显式校验并提示，不用 precision 在编辑时静默舍入')
      }
    })
    // 模板中直接拼接百分号的乘法会丢失输入口径；模型编辑与几何坐标换算不属于文本展示。
    if (/{{[^}]*\*\s*100[^}]*}}\s*%/.test(template)) report('百分比文本必须显式声明 ratio/percent 输入口径')
  }
  return [...new Set(violations)]
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const violations = auditNumbers(designSources())
  if (violations.length) { console.error(violations.join('\n')); process.exitCode = 1 }
  else console.log('数值展示共享入口检查通过。')
}
