import { describe, expect, it } from 'vitest'
import { auditControlRows, auditControlRowsTree } from '../../../scripts/check-control-rows.mjs'

const audit = (source: string) => auditControlRows([{ file: 'views/Fixture.vue', source }])

describe('操作行消费门禁', () => {
  it('真实消费者无逐控件尺寸补偿或局部高度覆盖', () => {
    expect(auditControlRowsTree()).toEqual([])
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
  it('跟踪共享组件的具名操作插槽，不污染正文内容', () => {
    expect(audit(`<template><AppWorkspacePane>
      <template #actions><AppSelect size="small" /></template>
      <AppSelect size="large" />
    </AppWorkspacePane></template>`)).toHaveLength(1)
  })
  it('追踪参与控件业务类和内部 wrapper，禁止通过局部样式补偿高度', () => {
    expect(audit(`<template><AppControlRow class="bar"><AppSelect class="choose" /></AppControlRow></template>
      <style>.choose :deep(.el-select__wrapper){min-height:40px}</style>`)).toHaveLength(1)
    expect(audit(`<template><AppControlRow class="bar" /></template>
      <style>.bar{height:32px}</style>`)).toHaveLength(1)
  })
  it('保留附属角色尺寸，边界内的行外编辑控件可独立声明尺寸', () => {
    expect(audit(`<template><AppControlRow>
      <AppCloseButton label="关闭预览" size="compact" /><el-tag size="small" />
      <el-button link size="small">详情</el-button>
      <AppDialog><AppSelect size="large" /></AppDialog>
      <AppForm><AppSelect size="large" /></AppForm>
    </AppControlRow></template>`)).toEqual([])
    expect(audit(`<template><AppControlRow><AppDialog><AppControlRow>
      <AppSelect size="large" />
    </AppControlRow></AppDialog></AppControlRow></template>`)).toHaveLength(1)
  })
})
