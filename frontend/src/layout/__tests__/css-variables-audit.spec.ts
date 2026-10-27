import { describe, expect, it } from 'vitest'
import { auditCssVariables, auditCssVariablesTree, cssVariableReferences } from '../../../scripts/check-css-variables.mjs'

const tokens = { file: 'styles/global.css', source: ':root {--app-space-2:8px;--app-space-3:12px}' }
const audit = (source: string, file = 'views/Fixture.vue') => auditCssVariables([tokens, { file,
  source: file.endsWith('.vue') && source.startsWith('<style>')
    ? '<template><div /></template>' + source : source,
}])

describe('CSS 变量统一门禁', () => {
  it('全量生产源码和锁定组件库的真实定义通过', () => {
    expect(auditCssVariablesTree()).toEqual([])
  })

  it.each([
    '<template><div /></template><style>.unit {margin-left:var(--space-2)}</style>',
    '<template><div style="gap:var(--space-2)" /></template>',
    '<template><div :style="{gap: \'var(--space-2)\'}" /></template>',
    'const style = { gap: "var(--space-2)" }',
    'const html = `<div style="gap:var(--space-2)"></div>`',
  ])('拦截 CSS、模板和脚本中的原缺陷：%s', source => {
    const file = source.startsWith('<') ? 'views/Fixture.vue' : 'utils/fixture.ts'
    expect(audit(source, file).join()).toContain('未定义 CSS 变量: --space-2')
  })

  it('报告实际文件和行号，注释及字符串内容不冒充变量引用', () => {
    expect(audit('<template><div /></template>\n<style>\n.unit {gap:var(--space-2)}\n</style>'))
      .toEqual(['views/Fixture.vue:3 未定义 CSS 变量: --space-2；使用有效变量或显式 fallback'])
    expect(audit('<style>/* gap:var(--missing) */ .unit {content:"var(--also-missing)";gap:var(--app-space-2)}</style>')).toEqual([])
  })

  it('支持局部、@property、模板对象及 setProperty 运行时定义', () => {
    expect(audit(`<script setup>
      document.documentElement.style.setProperty('--runtime-gap', '8px')
      const style = {'--object-gap':'12px'}
    </script><template><div :style="{'--template-gap': '8px'}" /></template>
    <style>@property --registered-gap {syntax:'<length>';inherits:true;initial-value:8px}
      .unit {--local-gap:var(--app-space-2);gap:var(--runtime-gap) var(--object-gap);
        padding:var(--template-gap) var(--local-gap) var(--registered-gap)}
    </style>`)).toEqual([])
    expect(audit('<template><div :style="\'--template-gap:8px;gap:var(--template-gap)\'" /></template>')).toEqual([])
  })

  it('从有限 map 推导运行时变量，未生成的名称仍然失败', () => {
    const runtime = `const vars = Object.fromEntries((['success','warning'] as const).map(name => [
      \`--border-\${name}\`, '8px']))`
    expect(auditCssVariables([tokens, {file:'theme.ts',source:runtime}, {
      file:'fixture.css',source:'.unit{gap:var(--border-success);padding:var(--border-warning)}',
    }])).toEqual([])
    expect(auditCssVariables([{file:'theme.ts',source:runtime}, {
      file:'fixture.css',source:'.unit{gap:var(--border-danger)}',
    }]).join()).toContain('--border-danger')
  })

  it('组件库定义按实际名称消费，禁止按 --el-* 前缀整包放行', () => {
    const external = [{file:'dependency.css',source:':root{--el-border-color:red}'}]
    expect(auditCssVariables([{file:'fixture.css',source:'.unit{border-color:var(--el-border-color)}'}], external)).toEqual([])
    expect(auditCssVariables([{file:'fixture.css',source:'.unit{border-color:var(--el-border-colour)}'}], external).join()).toContain('--el-border-colour')
  })

  it.each(['var(--optional, 8px)', 'var(--optional, var(--app-space-2))',
    'calc(var(--optional, max(8px, var(--app-space-2))) * 2)', 'var(--optional,)'])('合法 fallback 通过：%s', value => {
    expect(audit(`<style>.unit{gap:${value}}</style>`)).toEqual([])
  })

  it('嵌套 fallback 和别名中的未定义变量仍须失败', () => {
    expect(audit('<style>.unit{gap:var(--optional,var(--missing))}</style>').join()).toContain('--missing')
    expect(audit('<style>.unit{--local:var(--missing);gap:var(--local)}</style>').join()).toContain('--missing')
    expect(audit('<style>.unit{gap:var(--app-space-2,var(--missing))}</style>').join()).toContain('--missing')
    expect(cssVariableReferences('var(--optional, rgb(0,0,0))')).toMatchObject([{name:'--optional',fallback:true}])
    expect(cssVariableReferences('var(--missing /* , ignored */)')).toMatchObject([{name:'--missing',fallback:false}])
  })
})
