import postcss from 'postcss'
import { baseParse } from '@vue/compiler-dom'

// 仅登记真正的品牌/图形例外；普通面板不能因位于某文件而整文件豁免。
const graphicShapes = {
  'App.vue': ['.theme-option-signal', '.navigation-preview', '.nav-preview-content'],
  'components/SubScoreBars.vue': ['.cell'],
}

/** 静态门禁只检查可判定的配方漂移；真实焦点与组合态仍须在浏览器验收。 */
export function inspectBorderStyles(css, file) {
  const findings = []
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
