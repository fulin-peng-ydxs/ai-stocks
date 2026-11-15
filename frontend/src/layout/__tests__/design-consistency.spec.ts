import { FULL_SOURCE_AUDIT_TIMEOUT_MS } from './helpers/fullSourceAudit'
import { describe, expect, it } from 'vitest'
import { designSources } from '../../../scripts/design-source.mjs'
import { auditDateTimeConsumers, auditDesignConsistency, auditHeadings, auditPrimaryActions, auditSharedStyleRecipes, auditSpacingMotion, findStyleReuseCandidates } from '../../../scripts/check-design-consistency.mjs'

const sample = (source: string) => [{ file: 'views/Probe.vue', source: source.startsWith('<style>') ? '<template><div /></template>' + source : source }]
const primary = '<el-button type="primary">保存</el-button>'

describe('标题说明不能重新混入标题', () => {
  it.each([
    '<h3>结果（历史）</h3>', '<h2>结果(历史)</h2>', '<div role="heading">结果（历史）</div>',
    '<SettingsGroup title="参数（自动）" />', '<PageDrawer :title="name" />',
    '<template #header>结果（历史）</template>', '<div class="app-section-title">结果（历史）</div>',
    '<div class="block-title">交易（说明）</div>', '<span class="db-title">范围（在线）</span>',
  ])('拒绝静态及常量标题：%s', template => {
    expect(auditHeadings(sample('<script setup>const name = "结果（历史）"</script><template>' + template + '</template>'))).not.toEqual([])
  })
  it('标题中的帮助说明、正文括注与原生提示保持合法', () => {
    expect(auditHeadings(sample('<template><h3>结果<HelpHint text="说明（历史）" /></h3><p>备注（历史）</p><iframe title="图表（历史）" /></template>'))).toEqual([])
    expect(auditHeadings(sample('<template><el-radio><span class="option-title">仅本次（推荐）</span></el-radio><div class="block-title">交易<span class="sub">点行查看（不跳转）</span></div></template>'))).toEqual([])
  })
})

describe('间距和动效的消费门禁', () => {
  it.each(['padding:7px', 'margin-block:9px', 'padding:var(--app-space-2) 13px', 'transition:opacity 333ms linear', 'animation:pulse .5s ease', 'transition-duration:0.3s', 'transition:opacity var(--app-motion-content) ease'])('拒绝 CSS、内联和脚本 HTML 的违规配方：%s', css => {
    for (const source of [`<style>.probe{${css}}</style>`, `<template><div style="${css}" /></template>`, `<script setup>const html = '<b style="${css}">内容</b>'</script>`]) expect(auditSpacingMotion(sample(source))).not.toEqual([])
  })
  it('绑定对象不能绕过，非 CSS 的业务数字不误报', () => {
    expect(auditSpacingMotion(sample('<template><div :style="{padding: \'7px\', [\'transitionDuration\']: \'333ms\'}" /></template>'))).toHaveLength(2)
    expect(auditSpacingMotion(sample('<template><div :style="{padding: 7}" /></template>'))).not.toEqual([])
    expect(auditSpacingMotion(sample('<script setup>const base = {padding:"7px"}; const styles = {...base}</script><template><div :style="styles" /></template>'))).not.toEqual([])
    expect(auditSpacingMotion(sample('<script setup>const options = {padding:7, duration:333}</script>'))).toEqual([])
  })
  it('私有变量别名仍追踪真实间距和时长，共享动效 token 保留定义权限', () => {
    expect(auditSpacingMotion(sample('<style>.probe{--private-padding:7px;--private-duration:333ms;padding:var(--private-padding);transition:opacity var(--private-duration)}</style>'))).toHaveLength(2)
    expect(auditSpacingMotion(sample('<style>.probe{--local-ease:ease;transition:opacity var(--app-motion-content) var(--local-ease)}</style>'))).not.toEqual([])
    expect(auditSpacingMotion([{file:'styles/global.css',source:':root{--app-motion-content:180ms;--app-motion-ease:cubic-bezier(0.2,0,0,1)}'},...sample('<style>.probe{--local-duration:var(--app-motion-content);transition:opacity var(--local-duration) var(--app-motion-ease)}</style>')])).toEqual([])
  })
  it('允许 token、零重置、auto 对齐与非节奏几何，例外必须精确且仍有效', () => {
    expect(auditSpacingMotion(sample('<style>.probe{padding:var(--app-space-2);margin:0 auto;transform:translateX(7px);transition:none;transition-duration:0ms}</style>'))).toEqual([])
    const exception = { file: 'views/Probe.vue', selector: '.brand', property: 'animation', value: 'ticker 18s linear infinite', reason: '品牌循环' }
    const source = sample('<style>.brand{animation:ticker 18s linear infinite}</style>')
    expect(auditSpacingMotion(source, [exception], {verifyExceptions:true})).toEqual([])
    expect(auditSpacingMotion(source, [{...exception,reason:''}])).not.toEqual([])
    expect(auditSpacingMotion(sample('<style>.other{animation:ticker 18s linear infinite}</style>'), [exception])).not.toEqual([])
    expect(auditSpacingMotion(source, [{...exception,value:'ticker 19s linear infinite'}], {verifyExceptions:true})).toHaveLength(2)
  })
})

describe('实色主按钮的上下文与互斥条件', () => {
  it('拒绝同一区域、分开的表单以及组件别名中的重复强调', () => {
    for (const template of [primary + primary, `<AppForm>${primary}</AppForm><AppForm>${primary}</AppForm>`, '<Command type="primary"/><el-button :type="dirty ? \'primary\' : \'info\'" />']) {
      expect(auditPrimaryActions(sample('<script setup>import { ElButton as Command } from "element-plus"</script><template>' + template + '</template>'))).not.toEqual([])
    }
  })
  it('动态轻量属性、命名空间与动态组件仍检查实色可能状态', () => {
    expect(auditPrimaryActions(sample('<script setup>import * as EP from "element-plus"; import {ElButton as Command} from "element-plus"</script><template><EP.ElButton type="primary" :plain="busy"/><component :is="Command" type="primary"/></template>'))).not.toEqual([])
  })
  it('动态 type 的互斥强调合法，但两个可同时为主色的分支仍拒绝', () => {
    expect(auditPrimaryActions(sample('<template><el-button :type="dirty ? \'primary\' : \'info\'"/><el-button :type="dirty ? \'info\' : \'primary\'"/></template>'))).toEqual([])
    expect(auditPrimaryActions(sample('<template><el-button :type="dirty ? \'primary\' : \'info\'"/><el-button :type="ready ? \'primary\' : \'info\'"/></template>'))).not.toEqual([])
  })
  it('轻量语义按钮、独立弹层及互斥分支不会误报', () => {
    for (const template of [primary + '<el-button type="primary" plain />', primary + '<PageDrawer>' + primary + '</PageDrawer>', `<div v-if="editing">${primary}</div><div v-else>${primary}</div>`, `<div v-if="mode === 'a'">${primary}</div><div v-if="mode === 'b'">${primary}</div>`, `<div v-if="saved && editing">${primary}</div><div v-if="!saved">${primary}</div>`]) expect(auditPrimaryActions(sample('<template>' + template + '</template>'))).toEqual([])
  })
  it('复合分支和 computed 可证明互斥，OR 的枚举不被误判为互斥', () => {
    expect(auditPrimaryActions(sample('<script setup>const show = computed(() => ready.value && props.mode === "edit")</script><template><div v-if="!ready">' + primary + '</div><div v-if="show">' + primary + '</div></template>'))).toEqual([])
    expect(auditPrimaryActions(sample('<template><div v-if="mode === \'a\' || ready">' + primary + '</div><div v-if="mode === \'b\' || ready">' + primary + '</div></template>'))).not.toEqual([])
  })
})

describe('日期时间展示统一消费', () => {
  it.each(['row.created_at', "row.created_at.replace('T', ' ')", "row.created_at.slice(0, 19)", 'new Date(row.created_at).toLocaleString()', 'new Intl.DateTimeFormat().format(new Date(row.created_at))', 'new Date().toISOString()'])('拒绝原始时间和私有格式化：%s', expression => {
    expect(auditDateTimeConsumers(sample(`<template><span>{{ ${expression} }}</span></template>`))).not.toEqual([])
  })
  it('私有 formatter 和 HTML 文案截取被拒绝，数组截取、计算与提交日期保留原语义', () => {
    expect(auditDateTimeConsumers(sample('<script setup>const fmtTime = (s: string) => s.slice(0,19); const label = `${row.created_at.slice(0,19)}`</script>'))).not.toEqual([])
    expect(auditDateTimeConsumers(sample('<script setup>const rows = items.slice(0,10); const stamp = Date.parse(row.created_at.slice(0,19).replace(" ", "T")); const payload = rows.map(item => ({operated_at:item.operated_at.slice(0,19)}))</script>'))).toEqual([])
  })
  it('公共 formatter 和业务包装器合法，日期控件模型不是展示文本', () => {
    expect(auditDateTimeConsumers(sample('<script setup>import {formatDateTimeSeconds,formatClockTime} from \"@/utils/dateTime\";const fmtTime = (value: string) => formatDateTimeSeconds(value)</script><template><span>{{ fmtTime(row.created_at) }}</span><span>{{ formatClockTime(row.operated_at) }}</span><AppDatePicker v-model="form.operated_at" value-format="YYYY-MM-DDTHH:mm:ss" /></template>'))).toEqual([])
  })
})

describe('复用候选与统一执行', () => {
  it('相同 token 配方仍属于复用候选，不机械拒绝不同职责的相同外观', () => {
    const css = 'color:var(--el-text-color-secondary);font-size:var(--app-font-size-caption);padding:var(--app-space-2)'
    expect(findStyleReuseCandidates(sample(`<style>.first{${css}}.second{${css}}</style>`))).toHaveLength(1)
    expect(findStyleReuseCandidates(sample(`<style>.first{${css}}.second{display:flex}</style>`))).toEqual([])
  })
  it('已发布的共享配方不能换名复制，允许消费语义类后保留业务颜色', () => {
    const recipe = 'font-size:var(--app-font-size-data);line-height:var(--app-line-height-data);font-weight:var(--app-font-weight-section);font-variant-numeric:tabular-nums'
    const owner = {file:'styles/global.css',source:`.app-data-emphasis{${recipe}}`}
    expect(auditSharedStyleRecipes([owner, ...sample(`<style>.private{${recipe}}</style>`)])).not.toEqual([])
    expect(auditSharedStyleRecipes([owner, ...sample('<template><b class="app-data-emphasis private" /></template><style>.private{color:var(--el-color-primary)}</style>')])).toEqual([])
  })
  it.each(['kpi-lg', 'kpi-xl', 'page-title-sm'])('独立 KPI / 行情主值角色保留 %s，不误套普通数字强调配方', role => {
    const owner = { file: 'styles/global.css', source: '.app-data-emphasis{font-size:var(--app-font-size-data);line-height:var(--app-line-height-data);font-weight:var(--app-font-weight-section);font-variant-numeric:tabular-nums}' }
    const source = `<template><strong class="hero-value">收益</strong></template><style>.hero-value{font-size:var(--app-font-size-${role});line-height:var(--app-line-height-data);font-weight:var(--app-font-weight-strong);font-variant-numeric:tabular-nums}</style>`
    expect(auditSharedStyleRecipes([owner, ...sample(source)])).toEqual([])
  })
  it('统一入口执行全部守卫，生产全树和精确例外保持有效', () => {
    const source = `<template><h3>标题（说明）</h3>${primary}${primary}<span>{{ row.created_at }}</span></template><style>.probe{padding:7px;transition:opacity 333ms linear}</style>`
    const errors = auditDesignConsistency(sample(source)).join('\n')
    for (const text of ['标题不得', '游离刻度', '动效时长', '多个实色', '日期时间']) expect(errors).toContain(text)
    expect(auditDesignConsistency(designSources(), {verifyExceptions:true})).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)
})
