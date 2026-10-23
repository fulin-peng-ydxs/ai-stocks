import postcss from 'postcss'

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
