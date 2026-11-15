import { FULL_SOURCE_AUDIT_TIMEOUT_MS } from './helpers/fullSourceAudit'
import { describe, expect, it } from 'vitest'
import { auditSettingsStructure, auditSettingsStructureTree } from '../../../scripts/check-settings-structure.mjs'

const audit = (template: string) => auditSettingsStructure([
  // 依赖组件也提供源码，让门禁按结构推导容器角色，而非按业务名字猜测。
  { file: 'StockChartSettingSection.vue', source: '<template><PageSettingItem><input /></PageSettingItem></template>' },
  { file: 'fixture.vue', source: `<template>${template}</template>` },
])
describe('设置分组与叶子结构', () => {
  it('拒绝空标题及嵌套复合事项，支持 Pascal 和 kebab 标签', () => {
    expect(audit('<PageSettingItem label="范围"><template #actions><span>默认</span></template></PageSettingItem>')).toHaveLength(1)
    expect(audit('<PageSettingItem label="图表"><StockChartSettingSection /></PageSettingItem>')).toHaveLength(1)
    expect(audit('<page-setting-item><div><page-toggle-row /></div></page-setting-item>')).toHaveLength(1)
    expect(audit('<PageSettingItem><SettingsGroup><PageSettingItem><input /></PageSettingItem></SettingsGroup></PageSettingItem>').length).toBeGreaterThan(0)
  })
  it('分组承载叶子，叶子的枚举选项与帮助不产生下一层设置', () => {
    expect(audit(`<SettingsGroup title="范围">
      <PageSettingItem label="类型"><el-checkbox-group><el-checkbox>全部</el-checkbox></el-checkbox-group></PageSettingItem>
      <PageSettingItem label="数量"><template #help>说明</template><input /></PageSettingItem>
    </SettingsGroup>`)).toEqual([])
  })
  it('沿真实组件关系识别新复合设置和导入别名，不依赖业务组件白名单', () => {
    expect(auditSettingsStructure([
      { file: 'NewFields.vue', source: '<template><PageSettingItem><input /></PageSettingItem></template>' },
      { file: 'Consumer.vue', source: `<script setup>import FieldsAlias from './NewFields.vue'</script>
        <template><PageSettingItem><FieldsAlias /></PageSettingItem></template>` },
    ])).toHaveLength(1)
  })
  it('全部生产设置遵守结构约束', () => { expect(auditSettingsStructureTree()).toEqual([]) }, FULL_SOURCE_AUDIT_TIMEOUT_MS)
})
