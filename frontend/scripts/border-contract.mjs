import postcss from 'postcss'
import { baseParse } from '@vue/compiler-dom'
import { readFileSync } from 'node:fs'

export const { segmentedRoles } = JSON.parse(readFileSync(new URL('./design-contracts.json', import.meta.url), 'utf8'))

// 仅保留与普通表面不同的真实边界职责：自绘输入触发、整层浮层和图形预览。
const boundaryOwners = {
  'components/IconPicker.vue': ['.ip-trigger'],
  'components/PageDrawerSurface.vue': ['.page-drawer-surface'],
  'layout/components/LayoutComponentPreview.vue': ['.cp-input', '.cp-finput'],
}

// 仅登记真正的品牌/图形例外；普通面板不能因位于某文件而整文件豁免。
const graphicShapes = {
  'App.vue': ['.theme-option-signal', '.navigation-preview', '.nav-preview-content'],
  'components/SubScoreBars.vue': ['.cell'],
}

/** 静态门禁只检查可判定的配方漂移；真实焦点与组合态仍须在浏览器验收。 */
export function inspectBorderStyles(css, file) {
  const findings = []
  postcss.parse(css).walkRules(rule => {
    const border = rule.nodes.find(n => n.type === 'decl' && n.prop === 'border')
    const radius = rule.nodes.find(n => n.type === 'decl' && n.prop === 'border-radius')
    // 捕获完整普通表面配方，而非只检查是否使用了颜色变量。
    if (file !== 'styles/borders.css' && border && radius
      && /var\(--(?:app-border-(?:default|subtle)|el-border-color(?:-light|-lighter)?|page-settings-(?:section-)?border|chrome-border)(?:\s*[,)]|\s+$)/.test(border.value)
      && /var\(--(?:layout-(?:card|control)-radius|app-radius-(?:floating-section|item))(?:\s*[,)]|\s+$)/.test(radius.value)
      && !boundaryOwners[file]?.includes(rule.selector)) {
      findings.push({ line: border.source.start.line, message: `${rule.selector} 普通表面配方须接入 app-surface 或共享选择角色，不能在消费方重复维护。` })
    }
    if (rule.selector.includes('.app-interaction-card') && rule.selector.includes('::before')
      && border?.value.includes('--el-border-color-lighter')) {
      findings.push({ line: border.source.start.line, message: '交互卡片可见外沿必须消费表面轻边框，不能回退到分隔线。' })
    }
  })
  postcss.parse(css).walkDecls(decl => {
    const selector = decl.parent.selector ?? ''
    const brandShape = file === 'views/LoginView.vue' && /\.(?:login-|brand-|trend-|spark|mini-|visual-|lv-)/.test(selector)
    const graphicShape = graphicShapes[file]?.includes(selector)
    // 允许变量内部的兜底值，但变量不能豁免同一声明中并列写死的其它角。
    const shapeValue = decl.value.replace(/var\((?:[^()]|\([^()]*\))*\)/g, '')
    // 1~3px 是图例、拖拽标记等微图形；圆/胶囊属于明确形状，不当作普通矩形圆角。
    if (/^border(?:-(?:top|bottom)-(?:left|right))?-radius$/.test(decl.prop)
      && !brandShape && !graphicShape
      && [...shapeValue.matchAll(/(\d+(?:\.\d+)?)px/g)].some(([, px]) => Number(px) > 3 && Number(px) < 999)) {
      findings.push({ line: decl.source.start.line, message: `${selector} 普通圆角必须消费共享角色；品牌/图形例外须具名登记。` })
    }
    if (/^border(?:-(?:top|right|bottom|left))?(?:-color)?$/.test(decl.prop)
      && /#[\da-f]{3,8}\b|rgba?\(\s*\d/i.test(decl.value)) {
      findings.push({ line: decl.source.start.line, message: `${selector} 边框颜色必须消费主题或领域语义变量。` })
    }
    if (file.startsWith('views/') && /\.el-(?:input__wrapper|textarea__inner|range-editor|select__wrapper)/.test(selector)
      && /^(?:border(?:-color|-radius)?|box-shadow)$/.test(decl.prop) && !brandShape) {
      findings.push({ line: decl.source.start.line, message: '页面不得覆盖共享输入边框状态，请在 borders.css 适配真实控件变体。' })
    }
  })
  return findings
}

/** 显式登记主模式/主查询范围；普通参数默认中性，动态角色不能绕过登记。 */
export function inspectSegmentedRoles(template, file, roles = segmentedRoles) {
  const findings = []
  const seen = new Set()
  function inspect(node) {
    if (node.type !== 1) return
    if (node.tag === 'PageSegmented') {
      const attr = name => node.props.find(p => p.type === 6 && p.name === name)?.value?.content
      const label = attr('aria-label')
      const role = roles.find(r => r.file === file && r.label === label)
      const dynamic = node.props.some(p => p.type === 7 && p.name === 'bind' && ['tone', 'variant'].includes(p.arg?.content))
      if (dynamic || (attr('tone') === 'primary' || attr('variant') === 'tabs') && !role) {
        findings.push({ line: node.loc.start.line, message: '主色/页签分段须登记真实任务角色，普通参数及局部工具保持中性。' })
      }
      if (role) {
        seen.add(role.label)
        if (attr('tone') !== role.tone || (attr('variant') || 'contained') !== role.variant) {
          findings.push({ line: node.loc.start.line, message: `${label} 分段外观与登记角色不一致。` })
        }
      }
    }
    node.children.forEach(inspect)
  }
  baseParse(template).children.forEach(inspect)
  for (const role of roles.filter(r => r.file === file)) {
    if (!seen.has(role.label)) findings.push({ line: 1, message: `${role.label} 分段角色登记已失效。` })
  }
  return findings
}

/** 跟踪模板中的表面所有者，穿透状态层；独立弹层开始新的边界作用域。 */
export function inspectStockChartBoundaries(template) {
  const findings = []
  // 普通卡片可包含有间距的独立图区，不把任意祖先边框当作贴边宿主。
  const hosts = new Set(['AppWorkspacePane'])
  const overlays = new Set(['AppDialog', 'PageDrawer', 'AppDetailDrawer'])
  function inspect(node, host = false) {
    if (node.type !== 1) return
    if (overlays.has(node.tag)) host = false
    const classes = node.props.find(p => p.type === 6 && p.name === 'class')
      ?.value?.content.split(/\s+/) ?? []
    host ||= hosts.has(node.tag) || classes.includes('app-surface')
    if (node.tag === 'StockChartWorkspace') {
      const embedded = node.props.find(p => p.type === 6 && p.name === 'embedded')
      const bound = node.props.find(p => p.type === 7 && p.name === 'bind' && p.arg?.content === 'embedded')
      const spread = node.props.some(p => p.type === 7 && p.name === 'bind' && !p.arg)
      const isEmbedded = !(embedded && bound) && !spread && (
        !!embedded && (!embedded.value || embedded.value.content === '')
        || bound?.exp?.content.trim() === 'true'
      )
      if (host && !isEmbedded || !host && (embedded || bound && bound.exp?.content.trim() !== 'false')) {
        findings.push({ line: node.loc.start.line, message: host
          ? '已有宿主外框的股票画布必须显式声明 embedded，由共享配方去重外框。'
          : '独立股票画布必须保留外框，不得声明 embedded 或使用动态边界。' })
      }
    }
    node.children.forEach(child => inspect(child, host))
  }
  baseParse(template).children.forEach(node => inspect(node))
  return findings
}
