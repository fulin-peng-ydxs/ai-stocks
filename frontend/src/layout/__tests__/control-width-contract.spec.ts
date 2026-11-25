import { FULL_SOURCE_AUDIT_TIMEOUT_MS } from './helpers/fullSourceAudit'
import { readFileSync } from 'node:fs'
import postcss from 'postcss'
import { describe, expect, it } from 'vitest'
import { TABLE_CONTROL_WIDTHS } from '@/components/table/adaptiveColumnWidth'
import { auditControlWidths, auditDesignContracts, auditSharedStyles } from '../../../scripts/check-design-contracts.mjs'
import { auditComponentEntries, designSources } from '../../../scripts/design-source.mjs'

const audit = (source: string) => auditControlWidths([{ file: 'views/WidthProbe.vue', source }])

describe('输入与选择控件的容量门禁', () => {
  it.each(['el-input', 'el-input-number', 'AppSearchInput', 'AppSelect', 'AppFilterSelect',
    'AppDatePicker', 'TradeDatePicker', 'IndicatorSelect'])('拒绝 %s 的匿名固定容量', tag => {
    for (const property of ['width:173px', 'min-width:12rem', 'max-width:20ch', 'inline-size:173px', 'flex:0 0 173px']) {
      expect(audit(`<template><${tag} style="${property}" /></template>`).join()).toContain('控件宽度')
    }
  })

  it.each(['{width: w}', "{width: width || '130px'}", "{width: '100%'}",
    "{['width']: '173px'}", '{...styles}', 'styles', "'width:173px'"])(
    '动态样式不能绕过容量：%s', style => {
      expect(audit(`<template><AppSelect :style="${style.replaceAll('"', '&quot;')}" /></template>`)).not.toEqual([])
    },
  )

  it('跟踪业务 class、动态 class、容器查询、deep/global 和外部 CSS', () => {
    for (const css of ['.field{width:173px}', ':deep(.el-select){width:173px}',
      ':global(.field){width:173px}', '@container pane (width < 800px){.field{width:173px}}',
      '.field{--app-control-inline-width:173px}']) {
      expect(audit(`<template><AppSelect :class="{field: active}" /></template><style>${css}</style>`)).not.toEqual([])
    }
    expect(auditControlWidths([
      { file: 'views/WidthProbe.vue', source: '<template><AppSelect class="field" /></template>' },
      { file: 'styles/probe.css', source: '.field{width:173px}' },
    ])).not.toEqual([])
  })

  it('不能借私有 CSS 变量或单控件包裹层复制容量', () => {
    expect(audit('<template><div class="field"><div><TradeDatePicker /></div></div></template>'
      + '<style>.field{width:173px}</style>')).not.toEqual([])
    expect(audit('<template><AppSelect class="field" /></template>'
      + '<style>.field{--private-width:173px;width:var(--private-width)}</style>')).not.toEqual([])
  })

  it('导入别名和多层根包装器仍继承下拉容量契约', () => {
    expect(audit('<script setup>import Choice from "@/components/AppSelect.vue"</script>'
      + '<template><Choice style="width:173px" /></template>')).not.toEqual([])
    expect(auditControlWidths([
      { file: 'components/Choice.vue', source: '<template><AppSelect /></template>' },
      { file: 'components/OtherChoice.vue', source: '<template><Choice /></template>' },
      { file: 'views/WidthProbe.vue', source: '<template><OtherChoice style="width:173px" /></template>' },
    ])).not.toEqual([])
  })

  it('拒绝像素 width 属性和多选的第二套容量', () => {
    expect(audit('<template><AppSelect width="173px" /></template>')).not.toEqual([])
    expect(audit('<template><AppSelect :width="width" /></template>')).not.toEqual([])
    for (const extra of ['class="app-control-width-short"', 'width="short"']) {
      expect(audit(`<template><AppFilterSelect :visible-tag-count="3" ${extra}/></template>`)).not.toEqual([])
    }
    expect(audit('<template><AppFilterSelect :class="{\'app-control-width-short\': active}" /></template>')).not.toEqual([])
    expect(audit('<script setup>import Filters from "@/components/AppFilterSelect.vue"</script>'
      + '<template><Filters width="short" /></template>')).not.toEqual([])
    expect(audit('<template><AppFilterSelect :multiple="false" class="app-control-width-short" /></template>')).toEqual([])
  })

  it('公共档位、fill、自然伸缩、复合布局和装饰子元素不误报', () => {
    expect(audit(`<template><AppSelect width="short" class="field" />
      <AppFilterSelect :visible-tag-count="3" /><el-input class="app-control-width-fill" />
      <div class="grid"><TradeDatePicker /></div></template><style>
      .field{max-width:100%;min-width:0;flex:1 1 auto}
      .field .icon{width:14px}.field::before{width:14px}
      :root :is(.el-date-editor .clear-icon,.el-select__clear){width:16px}
      .grid{display:grid;grid-template-columns:repeat(2,minmax(180px,1fr))}
      .field{width:min(var(--app-control-width-long),30cqw)}
      </style>`)).toEqual([])
  })

  it('范围选择器仅允许登记的语义宽度透传，不放开其它动态表达式', () => {
    const source = (expression: string) => [{
      file: 'components/KlineRangeSelect.vue',
      source: `<template><AppSelect :width="${expression}" /></template>`,
    }]
    expect(auditControlWidths(source('width'))).toEqual([])
    expect(auditControlWidths(source('privateWidth'))).not.toEqual([])
    const roles = [{ className: 'el-select', tags: ['AppSelect'], properties: [], bindings: [{
      file: 'components/KlineRangeSelect.vue', tag: 'AppSelect', name: 'width',
      expression: 'width', reason: '范围控件的语义容量透传',
    }] }]
    expect(auditSharedStyles(source('width'), roles, { verifyOwners: true })).toEqual([])
    expect(auditSharedStyles(source('privateWidth'), roles, { verifyOwners: true }).join())
      .toContain('绑定归属已失效')
  })

  it('复用选择器解析后仍分别判断每个目标的排除条件，不受节点顺序影响', () => {
    const exempt = '<AppSelect class="field is-exempt" />'
    const protectedInput = '<el-input class="field" />'
    const style = '<style>.field:not(.is-exempt){width:173px}</style>'
    expect(audit(`<template>${exempt}</template>${style}`)).toEqual([])
    const expected = audit(`<template>${protectedInput}</template>${style}`)
    expect(expected).toHaveLength(1)
    expect(expected[0]).toContain('控件宽度')
    for (const nodes of [exempt + protectedInput, protectedInput + exempt]) {
      expect(audit(`<template>${nodes}</template>${style}`)).toEqual(expected)
    }
  })

  it('表格列的编辑容量与全部公共 CSS 档位保持一致', () => {
    const css = readFileSync(new URL('../../styles/global.css', import.meta.url), 'utf8')
    const values = new Map<string, string>()
    postcss.parse(css).walkDecls(decl => { values.set(decl.prop, decl.value) })
    for (const [kind, width] of Object.entries(TABLE_CONTROL_WIDTHS)) {
      expect(values.get(`--app-control-width-${kind}`), kind).toBe(`${width}px`)
    }
  })

  it('真实消费者通过，并且统一设计门禁确实调用宽度检查', () => {
    const sources = designSources()
    // 一次全树检查同时验证真实消费者与违规探针，避免为同一断言重复解析全树。
    const messages = auditDesignContracts([...sources, {
      file: 'views/WidthProbe.vue', source: '<template><el-input style="width:173px" /></template>',
    }])
    expect(messages.filter(message => !message.includes('WidthProbe.vue'))).toEqual([])
    expect(messages.some(message => message.includes('WidthProbe.vue') && message.includes('控件宽度'))).toBe(true)
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)
})

describe('页面空态入口', () => {
  it('DESIGN 不再指导业务页面直接复制底层 el-empty 示例', () => {
    const design = readFileSync(new URL('../../../../DESIGN.md', import.meta.url), 'utf8')
    expect(design).not.toMatch(/<el-empty\b/)
    expect(design).toContain('入口按[四态反馈总则]')
  })
  it('页面只消费共享状态入口，底层空态由 AppStateBlock 持有', () => {
    expect(auditComponentEntries([{file: 'views/EmptyProbe.vue', source: '<template><el-empty class="app-empty" /></template>'}]))
      .not.toEqual([])
    expect(auditComponentEntries([{file: 'views/EmptyProbe.vue', source: '<template><AppAsyncRegion /><AppStateBlock state="empty" /></template>'}]))
      .toEqual([])
    expect(auditComponentEntries([{file: 'components/AppStateBlock.vue', source: '<template><el-empty class="app-empty" /></template>'}]))
      .toEqual([])
  })
})
