import { FULL_SOURCE_AUDIT_TIMEOUT_MS } from './helpers/fullSourceAudit'
import { describe, expect, it } from 'vitest'
import { auditControlRows, auditControlRowsTree } from '../../../scripts/check-control-rows.mjs'

const audit = (source: string) => auditControlRows([{ file: 'views/Fixture.vue', source }])

describe('操作行消费门禁', () => {
  it.each([
    '<el-form-item><el-input-number/><AppSelect/></el-form-item>',
    '<el-form-item><div><el-input-number/><AppSelect/></div></el-form-item>',
    '<el-form-item><template v-if="show"><el-input-number/><AppSelect/></template></el-form-item>',
    '<el-form-item><el-input-number v-if="show"/><AppSelect/></el-form-item>',
    '<el-form-item><AppControlRow><div><el-input-number/><AppSelect/></div></AppControlRow></el-form-item>',
  ])('并列输入必须由实际间距容器承接：%s', source => {
    expect(audit(`<template>${source}</template>`).join()).toContain('并列输入控件')
  })

  it.each(['AppControlRow', 'AppTabToolbar'])('共享 %s 承接并列输入', tag => {
    expect(audit(`<template><el-form-item><${tag}><el-input-number/><AppSelect/></${tag}></el-form-item></template>`)).toEqual([])
  })

  it('共享纵横间距、单控件、互斥分支、分组内部选项和显式日期网格不误报', () => {
    for (const content of [
      '<div class="app-cluster-md"><el-input-number/><AppSelect/></div>',
      '<div class="app-stack-sm"><el-switch/><el-input-number/></div>',
      '<el-input-number/><AppFormHelp>说明</AppFormHelp>',
      '<AppSelect v-if="a"/><el-input-number v-else-if="b"/><el-input v-else/>',
      '<template v-if="a"><el-input/></template><template v-else><AppSelect/></template>',
      '<el-radio-group><el-radio-button/><el-radio-button/></el-radio-group>',
    ]) expect(audit(`<template><el-form-item>${content}</el-form-item></template>`)).toEqual([])
    const grid = '<template><el-form-item><div class="range"><TradeDatePicker/><span>—</span><TradeDatePicker/></div></el-form-item></template>'
    expect(audit(grid + '<style>.range{display:grid;grid-template-columns:1fr auto 1fr;gap:var(--app-space-2)}</style>')).toEqual([])
    expect(audit(grid + '<style>.range{display:grid;grid-template-columns:1fr auto 1fr}</style>').join()).toContain('并列输入控件')
  })

  it.each(['margin-left:8px', 'margin-right:var(--app-space-2)', 'margin-inline-start:8px',
    'margin:8px', 'margin:0 8px', 'margin:0 0 0 8px'])('拒绝控件用私有 margin 补间距：%s', declaration => {
    const source = '<template><el-form-item><AppControlRow><el-input-number/><AppSelect class="unit"/></AppControlRow></el-form-item></template>'
    expect(audit(source + `<style>.unit{${declaration}}</style>`).join()).toContain('水平 margin')
    expect(audit(`<template><el-form-item><AppSelect style="${declaration}"/></el-form-item></template>`).join()).toContain('水平 margin')
  })

  it('动态对象和深层选择器也拦截，零值、垂直间距与自动对齐不误报', () => {
    expect(audit('<template><el-form-item><AppSelect :style="{marginLeft: gap}"/></el-form-item></template>').join()).toContain('水平 margin')
    expect(audit('<template><el-form-item><AppSelect :style="{[\'margin-inline-start\']: \'8px\'}"/></el-form-item></template>').join()).toContain('水平 margin')
    expect(audit('<template><el-form-item><AppSelect/></el-form-item></template><style>:deep(.el-select){margin-left:8px}</style>').join()).toContain('水平 margin')
    expect(audit('<template><el-form-item><AppSelect style="margin-left:auto;margin:8px 0" :style="{marginRight:0}"/></el-form-item></template>')).toEqual([])
  })

  it('真实消费者无逐控件尺寸补偿或局部高度覆盖', () => {
    expect(auditControlRowsTree()).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)
  it('Grid 操作行声明列轨道，避免隐式列按内容收缩；不限制内部普通网格', () => {
    const template = '<template><AppControlRow class="tools"><div class="inner" /></AppControlRow></template>'
    for (const display of ['grid', 'inline-grid']) {
      expect(audit(`${template}<style>.tools {display:${display}}</style>`)).toHaveLength(1)
      expect(audit(`${template}<style>@media (max-width:900px) {.tools {display:${display}}}</style>`))
        .toHaveLength(1)
      for (const columns of ['minmax(0, 1fr)', 'repeat(auto-fit, minmax(240px, 1fr))']) {
        expect(audit(`${template}<style>.tools {display:${display};grid-template-columns:${columns}}</style>`))
          .toEqual([])
      }
    }
    expect(audit(`${template}<style>.tools .inner {display:grid}</style>`)).toEqual([])
  })
  it('拒绝静态/动态 size、内联高度、未知样式和整包绑定', () => {
    for (const props of ['size="small"', ':size="mode"', 'style="height:24px"',
      ':style="{ minHeight: h }"', ':style="privateStyle"', 'v-bind="props"']) {
      expect(audit(`<template><AppControlRow><AppSelect ${props} /></AppControlRow></template>`))
        .not.toEqual([])
    }
    expect(audit('<template><AppControlRow style="height:24px" /></template>')).toHaveLength(1)
    expect(audit('<template><AppControlRow><AppSelect :style="{width: w}" /></AppControlRow></template>'))
      .toEqual([])
  })
  it.each(['actions', 'toolbar', 'footer'])('跟踪共享组件的%s插槽，不污染正文内容', slot => {
    expect(audit(`<template><AppWorkspacePane>
      <template #${slot}><AppSelect size="small" /></template>
      <AppForm size="large"><AppSelect /></AppForm>
    </AppWorkspacePane></template>`)).toHaveLength(1)
  })
  it('追踪参与控件业务类和内部 wrapper，禁止通过局部样式补偿高度', () => {
    expect(audit(`<template><AppControlRow class="bar"><AppSelect class="choose" /></AppControlRow></template>
      <style>.choose :deep(.el-select__wrapper){min-height:40px}</style>`)).toHaveLength(1)
    expect(audit(`<template><AppControlRow class="bar" /></template>
      <style>.bar{height:32px}</style>`)).toHaveLength(1)
  })
  it('保留附属角色尺寸，独立表单通过整体尺寸声明层级', () => {
    expect(audit(`<template><AppControlRow>
      <AppCloseButton label="关闭预览" size="compact" /><el-tag size="small" />
      <el-button link size="small">详情</el-button>
      <AppDialog><AppForm size="large"><AppSelect /></AppForm></AppDialog>
      <AppForm size="large"><AppSelect /></AppForm>
    </AppControlRow></template>`)).toEqual([])
    expect(audit(`<template><AppControlRow><AppDialog><AppControlRow>
      <AppSelect size="large" />
    </AppControlRow></AppDialog></AppControlRow></template>`)).toHaveLength(1)
  })

  it('行外和普通包装层也拦截各自定档，复用插槽由共享动作行承接', () => {
    for (const tag of ['el-button', 'AppSelect', 'AppSearchInput', 'PageSegmented', 'el-input-number']) {
      expect(audit(`<template><section><div><${tag} size="small" /></div></section></template>`))
        .toHaveLength(1)
    }
    expect(audit(`<template><TradeDirectionGroupGrid><template #actions>
      <el-button size="small">添加</el-button>
    </template></TradeDirectionGroupGrid></template>`)).toHaveLength(1)
    expect(audit(`<template><AppControlRow size="small"><el-button>紧凑附属操作</el-button></AppControlRow>
      <AppDataTable><AppTableColumn><AppSelect size="small" /></AppTableColumn></AppDataTable>
    </template>`)).toEqual([])
  })

  it('分段宽度门禁覆盖业务类、媒体查询、内联样式和动态逃逸', () => {
    for (const property of ['width:360px', 'min-width:240px', 'max-width:80%', 'flex:1', 'padding:8px']) {
      expect(audit(`<template><section><PageSegmented class="business-choice" /></section></template>
        <style>@container app-viewport (max-width:900px) {.business-choice {${property}}}</style>`))
        .toHaveLength(1)
      expect(audit(`<template><PageSegmented style="${property}" /></template>`)).toHaveLength(1)
    }
    for (const binding of [':style="widths"', ':class="classes"', 'v-bind="options"']) {
      expect(audit(`<template><PageSegmented ${binding} /></template>`)).toHaveLength(1)
    }
    expect(audit(`<template><PageSegmented fill class="choice" /></template>
      <style>.choice {margin-bottom:12px; align-self:start}</style>`)).toEqual([])
    expect(auditControlRows([{ file: 'styles/fixture.css', source: '.page-segmented{width:360px}' }]))
      .toHaveLength(1)
  })

  it('普通表单和设置字段继承统一档位，表格行内与附属动作保留角色边界', () => {
    for (const field of ['AppSelect', 'el-input-number', 'IndicatorParamFields', 'PageSegmented']) {
      for (const host of ['AppForm', 'PageSettingItem']) {
        expect(audit(`<template><${host}><div><${field} size="small" /></div></${host}></template>`))
          .toHaveLength(1)
      }
    }
    expect(audit(`<template><AppForm><AppControlRow size="small"><AppSelect /></AppControlRow>
      <AppDataTable><AppTableColumn><el-input-number size="small" /></AppTableColumn></AppDataTable>
      <AppStatusNotice><el-button size="small">重试</el-button></AppStatusNotice>
      <AppIconButton size="sm" label="复制" />
    </AppForm></template>`)).toEqual([])
  })
})
