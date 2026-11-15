import { FULL_SOURCE_AUDIT_TIMEOUT_MS } from './helpers/fullSourceAudit'
import { describe, expect, it } from 'vitest'
import { auditTableHeaders, auditTableHeaderTree } from '../../../scripts/check-table-headers.mjs'
import { resolveTableHeader } from '@/components/table/tableHeader'

describe('表头不使用括号', () => {
  const audit = (template: string) => auditTableHeaders([{ file: 'sample.vue', source: `<template>${template}</template>` }])
  it('拒绝静态、绑定字面量和自定义表头中的中英文括号', () => {
    expect(audit('<AppTableColumn label="市值（元）"/>')).toHaveLength(1)
    expect(audit('<app-table-column label="市值（元）"/>')).toHaveLength(1)
    expect(audit('<AppTableColumn :label="\'收益(%)\'"/>')).toHaveLength(1)
    expect(audit('<AppTableColumn label="市值"><template #header>市值（元）</template></AppTableColumn>')).toHaveLength(1)
    expect(audit('<table><th>名称(说明)</th></table>')).toHaveLength(1)
  })
  it('允许字段标签和正文括号，不把函数调用语法当成可见文案', () => {
    expect(audit('<el-form-item label="资金（元）"/><AppTableColumn :label="display(field)" header-meta="元"/><el-card><template #header><HelpTip>收益(公式)</HelpTip></template></el-card>')).toEqual([])
  })
  it('动态表头保留括注内容并清理辅助元信息中的括号', () => {
    expect(resolveTableHeader('收益(%)', '净额（扣费）')).toEqual({ label: '收益', headerMeta: '% · 净额 扣费' })
    expect(resolveTableHeader('名称（未闭合')).toEqual({ label: '名称 未闭合', headerMeta: '' })
  })
  it('所有当前 Vue 表头符合约束', () => { expect(auditTableHeaderTree()).toEqual([]) }, FULL_SOURCE_AUDIT_TIMEOUT_MS)
})
