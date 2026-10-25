import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { auditComponentEntries, designContracts, designSources } from '../../../scripts/design-source.mjs'
import {
  auditColorSources, auditDesignContracts, auditDesignStateContract, auditSharedStyles,
  renderDesignContract,
} from '../../../scripts/check-design-contracts.mjs'

const sample = (source: string, file = 'views/GateProbe.vue') => [{ file, source }]
const template = '<template><ul class="list"><li class="row app-interaction-list-item--outlined"><span class="name app-list-item-trigger">方案</span></li><li class="other" /></ul></template>'
const globalCss = readFileSync(resolve('src/styles/global.css'), 'utf8')

describe('共享交互的覆盖门禁', () => {
  it.each([
    '.row:hover { background: red; }',
    '.row:hover .name { background: red; }',
    '.row:has(> .app-list-item-trigger:active) { background: red; }',
    '.row:is(:hover, :active) { border-color: red; }',
    '.list li { box-shadow: none; }',
    '.row:deep(.el-button) { background-color: red; }',
    '.row:is(:not(.app-interaction-list-item--outlined), :hover) { background: red; }',
    '.row { --app-interaction-selected-background: var(--el-color-danger); }',
  ])('拒绝复合选择器或后代覆盖：%s', css => {
    expect(auditSharedStyles(sample(`${template}<style scoped>${css}</style>`))).not.toEqual([])
  })

  it('外部 CSS 也追踪同一角色，不能转移文件逃避检查', () => {
    expect(auditSharedStyles([...sample(template), { file: 'styles/private.css', source: '.row:hover .name { background: red; }' }])).not.toEqual([])
  })

  it.each([
    'style="background: red"',
    ':style="{ backgroundColor: color }"',
    ':style="{ ...styles }"',
    ':style="styles"',
    'v-bind="attrs"',
  ])('拒绝角色内联或不可确认的覆盖：%s', binding => {
    expect(auditSharedStyles(sample(`<template><div class="app-interaction-list-item--outlined" ${binding}/></template>`))).not.toEqual([])
  })

  it('保留必要布局、无关兄弟样式和明确排除角色的普通样式', () => {
    for (const css of ['.row { padding: 8px; }', '.row + .other { background: red; }', '.other:has(.row:is(:has(.nested))) { background: red; }', '.row:not(.app-interaction-list-item--outlined, .other) { background: red; }']) {
      expect(auditSharedStyles(sample(`${template}<style scoped>${css}</style>`)), css).toEqual([])
    }
  })
})

describe('组件真实来源与唯一持有者', () => {
  it.each([
    '<template><el-table/></template>',
    '<template><ElTable/></template>',
    '<script setup>import {ElTable as RawTable} from "element-plus"</script><template><RawTable/></template>',
    '<script setup>import * as EP from "element-plus"; const C = EP.ElTable</script><template><component :is="C"/></template>',
    '<script setup>import * as EP from "element-plus"; const C = EP["ElTable"]</script>',
    '<script setup>import C from "element-plus/es/components/table/index"</script><template><C/></template>',
    '<template><component :is="\'el-table\'"/></template>',
    '<script setup>const C = resolveComponent("ElTable")</script>',
    '<script setup>const render = () => h("el-table", {})</script>',
    '<script setup>const C = "el-table"</script><template><component :is="C"/></template>',
    '<script setup>const C = "el-table"; const alias = C</script><template><component :is="enabled ? alias : \'div\'"/></template>',
    '<script setup>const C = "el-table"; const render = () => h(C, {})</script>',
  ])('不能通过别名、深路径、动态入口绕过共享组件', source => {
    expect(auditComponentEntries(sample(source))).not.toEqual([])
  })

  it('所有受控库组件仅允许在自身持有者中出现，非持有者和近似文件名不放行', () => {
    for (const [name, rule] of Object.entries(designContracts.entryPoints)) {
      const source = `<template><${name}/></template>`
      expect(auditComponentEntries(sample(source)), name).not.toEqual([])
      if (rule.owner) {
        expect(auditComponentEntries(sample(source, rule.owner)), name).toEqual([])
        expect(auditComponentEntries(sample(source, `views/${rule.owner}`)), name).not.toEqual([])
      }
    }
  })

  it('允许共享封装、正常库控件和纯类型导入', () => {
    expect(auditComponentEntries(sample('<script setup lang="ts">import type { ElTable } from "element-plus"; import { ElMessage } from "element-plus"</script><template><AppDataTable/><el-button/></template>'))).toEqual([])
  })
})

describe('跨语言颜色来源', () => {
  it.each([
    '<template><span/></template><style>.score { color: #123abc; background: #123abc; }</style>',
    '<template><span style="border: 1px solid #123abc"/></template>',
    '<template><span :style="{border: \'1px solid #123abc\'}"/></template>',
    '<script setup>const style = { color: "#123abc" }</script>',
    '<script setup>element.style.color = "#123abc"</script>',
    '<script setup>const html = `<span style="color:#123abc">${value}</span>`</script>',
  ])('拒绝 CSS、模板及脚本中的私有色值', source => {
    expect(auditColorSources(sample(source), [])).not.toEqual([])
  })

  it('token 不能掩盖同一声明中并列写死的颜色', () => {
    expect(auditColorSources(sample('<template><span/></template><style>.x{background:linear-gradient(var(--el-color-primary),#123abc)}</style>'), [])).not.toEqual([])
    expect(auditColorSources(sample('<template><span/></template><style>.x{background:color-mix(in srgb,var(--el-color-primary) 80%,white)}</style>'), [])).toEqual([])
  })

  it('色值例外精确到文件、声明和值，并要求理由；过期例外会失败', () => {
    const exception = { file: 'views/GateProbe.vue', selector: '.x', property: 'color', value: '#123abc', reason: '用户配色输入样板' }
    const source = '<template><span/></template><style>.x{color:#123abc}</style>'
    expect(auditColorSources(sample(source), [exception])).toEqual([])
    expect(auditColorSources(sample(source.replace('.x', '.y')), [exception])).not.toEqual([])
    expect(auditColorSources(sample(source), [{ ...exception, reason: '' }])).not.toEqual([])
    expect(auditColorSources([{ file: 'styles/global.css', source: ':root {}' }], [exception])).not.toEqual([])
  })
})

describe('源码与文档消费同一状态契约', () => {
  const design = renderDesignContract()
  it('代码、文档和契约一致时通过', () => {
    expect(auditDesignStateContract(globalCss, design)).toEqual([])
  })
  it('改写文档、重复定义、状态冲突和额外局部配方均失败', () => {
    expect(auditDesignStateContract(globalCss, design.replace('描边列表选中', '新状态'))).not.toEqual([])
    expect(auditDesignStateContract(globalCss, `${design}\n${design}`)).not.toEqual([])
    expect(auditDesignStateContract(globalCss, `${design}\n.app-interaction-list-item 禁止左线`)).not.toEqual([])
    expect(auditDesignStateContract(globalCss.replace('(hover: hover) and (pointer: fine)', '(hover: none)'), design)).not.toEqual([])
    expect(auditDesignStateContract(globalCss.replace('6%, var(--el-bg-color)', '40%, var(--el-bg-color)'), design)).not.toEqual([])
    expect(auditDesignStateContract(`${globalCss}\n.app-interaction-list-item--outlined.active {background:red}`, design)).not.toEqual([])
    expect(auditDesignStateContract(globalCss.replace('border-color: var(--el-color-primary);\n}', 'border-color: var(--el-color-primary);\n  background: red;\n}'), design)).not.toEqual([])
  })
  it('全树真实消费方通过同一构建检查器', () => {
    expect(auditDesignContracts(designSources())).toEqual([])
  })
})
