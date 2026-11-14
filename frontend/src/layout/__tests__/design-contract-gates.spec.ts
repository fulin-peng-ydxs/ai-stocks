import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { auditComponentEntries, auditStyleComponents, designContracts, designSources } from '../../../scripts/design-source.mjs'
import {
  auditButtonKinds, auditButtonStates, auditColorSources, auditDesignContracts, auditDesignStateContract, auditSharedStyles,
  auditRuntimeStyles, auditMessagePolicy, renderDesignContract,
} from '../../../scripts/check-design-contracts.mjs'

const sample = (source: string, file = 'views/GateProbe.vue') => [{ file, source }]
const template = '<template><ul class="list"><li class="row app-interaction-list-item--outlined"><span class="name app-list-item-trigger">方案</span></li><li class="other" /></ul></template>'
const globalCss = readFileSync(resolve('src/styles/global.css'), 'utf8')

describe('全局消息时序归属', () => {
  it.each([
    "import { ElMessage } from 'element-plus'; ElMessage({ message: '失败', duration: 0 })",
    "import { ElMessage as notify } from 'element-plus'; notify.error({ message: '失败', showClose: true })",
    "import * as EP from 'element-plus'; EP.ElMessage.warning({ message: '失败', ['duration']: 8000 })",
    "import { ElMessage } from 'element-plus'; const options = { showClose: true }; ElMessage({ ...options, message: '失败' })",
    "import { ElMessage } from 'element-plus'; const options = { duration: 0 } as const; ElMessage.error(options)",
    "import { ElMessage } from 'element-plus'; const notify = ElMessage; const warn = notify.warning; warn({ message: '失败', duration: 0 })",
    "import { ElMessage } from 'element-plus'; const { error: notify } = ElMessage; notify({ message: '失败', showClose: true })",
    "import { ElMessage } from 'element-plus'; function first() { const options = { duration: 0 }; ElMessage(options) } function second() { const options = { message: '正常' }; ElMessage(options) }",
  ])('拒绝页面自定消息时长和关闭方式：%s', script => {
    expect(auditMessagePolicy(sample(`<script setup>${script}</script>`))).not.toEqual([])
  })

  it('允许内容和级别，确认框的关闭策略独立；Provider 只归应用根所有', () => {
    const script = "import { ElMessage, ElMessageBox } from 'element-plus'; "
      + "ElMessage({ type: 'error', message: '来源数据未补齐' }); ElMessage.success('成功'); "
      + "ElMessageBox.confirm('确认操作', { showClose: false })"
    expect(auditMessagePolicy(sample(`<script setup>${script}</script>`))).toEqual([])
    const provider = '<script setup>import { APP_MESSAGE_POLICY } from "@/utils/messagePolicy"</script>'
      + '<template><el-config-provider :message="APP_MESSAGE_POLICY"><div /></el-config-provider></template>'
    expect(auditMessagePolicy(sample(provider))).not.toEqual([])
    expect(auditMessagePolicy(sample(provider, 'App.vue'))).toEqual([])
    expect(auditMessagePolicy(designSources())).toEqual([])
  })

  it.each([
    '<template><el-config-provider v-bind="{ message: { duration: 0 } }" /></template>',
    '<script setup>const props = { message: { showClose: true } }</script><template><ElConfigProvider v-bind="props" /></template>',
    '<script setup>import { ElConfigProvider as Provider } from "element-plus"; const props = { message: { duration: 0 } }</script><template><Provider v-bind="{...props}" /></template>',
    '<script setup>import * as EP from "element-plus"; const props = { message: { duration: 0 } }</script><template><EP.ElConfigProvider v-bind="props" /></template>',
    '<script setup>import { ElMessage as notify } from "element-plus"</script><template><button @click="notify({message: \'失败\', duration: 0})" /></template>',
  ])('拒绝批量绑定和模板调用绕过消息策略：%s', source => {
    expect(auditMessagePolicy(sample(source))).not.toEqual([])
  })

  it('变量和消息入口按词法作用域解析，不受别的函数或参数同名影响', () => {
    const source = `import { ElMessage } from 'element-plus';
      function first() { const options = { message: '正常' }; ElMessage(options) }
      function second() { const options = { duration: 0 }; return options }
      function third(ElMessage: Function) { ElMessage({ duration: 0 }) }`
    expect(auditMessagePolicy(sample(`<script setup>${source}</script>`))).toEqual([])
    expect(auditMessagePolicy(sample('<template><ElConfigProvider v-bind="{size: \'small\'}" /></template>'))).toEqual([])
  })

  it('应用根必须消费真实全局策略，不能删掉 Provider 或用同名局部对象代替', () => {
    expect(auditMessagePolicy(sample('<template><div /></template>', 'App.vue'))).not.toEqual([])
    expect(auditMessagePolicy(sample('<script setup>const APP_MESSAGE_POLICY = { duration: 0 }</script>'
      + '<template><ElConfigProvider :message="APP_MESSAGE_POLICY" /></template>', 'App.vue'))).not.toEqual([])
  })
})

describe('重置、运行时写入及新增控件的闭环门禁', () => {
  it.each([
    '<template><el-button class="probe"/></template><style>.probe { all: unset; }</style>',
    '<template><div/></template><style>* { all: initial; }</style>',
    '<template><div/></template><style>:global(*) { ALL: revert-layer; }</style>',
    '<template><el-button style="all: inherit"/></template>',
    '<template><div :style="{ all: reset }"/></template>',
    '<template><div :style="\'all: unset\'"/></template>',
    '<template><div :style="{ [\'all\']: \'unset\' }"/></template>',
  ])('不能用批量重置绕过受保护属性：%s', source => {
    expect(auditSharedStyles(sample(source))).not.toEqual([])
  })

  it.each([
    'el.style.padding = "40px"',
    'el["style"]["padding"] = value',
    'el.style[property] = value',
    'el.style.cssText += styles',
    'el.style = styles',
    'delete el.style.height',
    'el.style.setProperty("padding", "40px")',
    'el.style.removeProperty("height")',
    'const styles = el.style; styles.padding = value',
    'let styles; styles = el.style; styles.padding = value; styles = {}',
    'const write = el.style.setProperty',
    'const { setProperty: write } = el.style',
    'Object.assign(el.style, { padding: value })',
    'Object.defineProperty(el.style, "padding", { value })',
    'Reflect.set(el.style, "padding", value)',
    'el.setAttribute("style", styles)',
    'el.setAttribute("STYLE", styles)',
    'el.setAttribute(attribute, styles)',
    'const sheet = new CSSStyleSheet(); sheet.insertRule(rule)',
    'const sheet = new CSSStyleSheet(); sheet.replaceSync(rule)',
    'const sheet = new CSSStyleSheet(); sheet.replace(rule)',
    'document.adoptedStyleSheets = sheets',
    'const style = document.createElement("style"); style.textContent = rules',
    'const styles = el.style; mutate(styles)',
    'const getStyles = () => { return el.style }',
    'const getStyles = () => el.style; getStyles().padding = value',
    'const holder = [el.style]; holder[0].padding = value',
    'el.setAttributeNS(null, "style", styles)',
    'el.removeAttribute("style")',
    'h("button", { style: { padding: "40px" } })',
    'h("button", { STYLE: "padding:40px" })',
    'const props = { style: styles }; h("button", props)',
    'import { h as render } from "vue"; render("button", {style: styles})',
    'import * as Vue from "vue"; Vue.h("button", {style: styles})',
    'const render = h; render("button", {style: styles})',
    'h("button", { ...attrs })',
    'h("button", props)',
  ])('脚本不能绕过共享入口：%s', script => {
    expect(auditRuntimeStyles(sample(`<script setup>${script}</script>`))).not.toEqual([])
    expect(auditRuntimeStyles([{ file: 'utils/probe.ts', source: script }])).not.toEqual([])
  })

  it('读取计算样式、普通配置及字符串 replace 不误报', () => {
    const source = 'const style = getComputedStyle(el); const value = style.padding; const color = el.style.getPropertyValue("color"); const options = {padding: 20}; const text = value.replace("px", ""); h("span", "内容"); h("div", null); h("div", [h("span")]); h("div", () => "插槽")'
    expect(auditRuntimeStyles([{ file: 'utils/probe.ts', source }])).toEqual([])
  })

  it('运行时授权精确限制目标、操作、属性，扩展整包也不能放行', () => {
    const file = 'utils/measure.ts'
    const owner = { file, operation: 'Object.assign', target: 'probe.style', properties: ['width'], reason: '测量副本' }
    const run = (source: string, owners = [owner]) => auditRuntimeStyles([{ file, source }], owners, { verifyOwners: true })
    expect(run('Object.assign(probe.style, { width })')).toEqual([])
    for (const source of ['Object.assign(other.style, { width })', 'Object.assign(probe.style, { width, padding })', 'Object.assign(probe.style, { width }, { padding })', 'Object.assign(probe.style, { width }, extra)', 'probe.style.width = width']) {
      expect(run(source), source).not.toEqual([])
    }
    expect(auditRuntimeStyles([{ file: 'views/measure.ts', source: 'Object.assign(probe.style, { width })' }], [owner])).not.toEqual([])
    expect(run('Object.assign(probe.style, { width })', [{ ...owner, properties: ['width', 'height'] }])).not.toEqual([])
    expect(run('const value = 1')).not.toEqual([])
  })

  it('动态属性只接受共享入口登记的完整表达式，复制或篡改仍失败', () => {
    const expression = 'target.style.setProperty(variable, value)'
    const owner = {file:'utils/density.ts',operation:'setProperty',target:'target.style',expression,reason:'密度转发'}
    expect(auditRuntimeStyles([{file:owner.file,source:expression}], [owner], {verifyOwners:true})).toEqual([])
    expect(auditRuntimeStyles([{file:owner.file,source:expression.replace('value)', 'other)')}], [owner])).not.toEqual([])
    expect(auditRuntimeStyles([{file:'views/density.ts',source:expression}], [owner])).not.toEqual([])
  })

  it.each([
    '<template><el-new-control/></template>',
    '<script setup>import { ElNewControl as Alias } from "element-plus"</script><template><Alias/></template>',
    '<script setup>import * as EP from "element-plus"; const control = EP.ElNewControl</script>',
    '<script setup>import Control from "element-plus/es/components/new-control/index"</script>',
    '<script setup>const name = "el-new-control"</script><template><component :is="name"/></template>',
    '<template><AppNewControl/></template>',
    '<script setup>import Alias from "@/components/AppNewControl.vue"</script><template><Alias/></template>',
  ])('新增控件不能静默漏登记：%s', source => {
    expect(auditStyleComponents(sample(source))).not.toEqual([])
  })

  it('未消费的共享文件和以基础控件为根的包装器也必须登记', () => {
    expect(auditStyleComponents(sample('<template><div/></template>', 'components/AppNewControl.vue'))).not.toEqual([])
    expect(auditStyleComponents(sample('<template><el-input/></template>', 'components/CustomInput.vue'))).not.toEqual([])
    expect(auditStyleComponents(sample('<script setup>import Alias from "@/components/AppSelect.vue"</script><template><Alias/></template>', 'components/CustomInput.vue'))).not.toEqual([])
    expect(auditStyleComponents([{ file: 'components/AppNewControl.ts', source: 'export default defineComponent({})' }])).not.toEqual([])
    expect(auditStyleComponents(sample('<template><div><el-input/></div></template>', 'views/BusinessView.vue'))).toEqual([])
  })

  it('专项登记必须有真实入口与依据，重复和失效登记均失败', () => {
    const sources = sample('<template><AppNewControl/></template>', 'components/AppNewControl.vue')
    const owner = {tags:['AppNewControl'],owner:'components/AppNewControl.vue',reason:'专用结构组合'}
    const run = (delegates = [owner]) => auditStyleComponents(sources, undefined, delegates, {verifyRegistry:true})
    expect(run()).toEqual([])
    expect(run([{...owner,owner:'components/Missing.vue'}])).not.toEqual([])
    expect(run([{...owner,reason:''}])).not.toEqual([])
    expect(run([owner,owner])).not.toEqual([])
    expect(run([{...owner,tags:['AppUnusedControl']}])).not.toEqual([])
    expect(auditStyleComponents(sample('<template><AppSelect/></template>'))).toEqual([])
  })

  it('专项登记不会解除根控件包装器的属性保护，嵌套包装仍继承同一角色', () => {
    const sources = [
      {file:'components/SpecialSelect.vue',source:'<template><AppSelect/></template>'},
      {file:'components/NestedSelect.vue',source:'<template><SpecialSelect/></template>'},
      ...sample('<template><NestedSelect class="probe"/></template><style>.probe {font-size:var(--app-font-size-caption)}</style>'),
    ]
    expect(auditSharedStyles(sources)).not.toEqual([])
    expect(auditStyleComponents(sources)).not.toEqual([])
    expect(auditSharedStyles([
      {file:'components/Workspace.vue',source:'<template><div/><PageDrawer title="详情"/></template>'},
      ...sample('<template><Workspace class="workspace"/></template><style>.workspace{min-height:0}</style>'),
    ])).toEqual([])
  })

  it('统一契约入口同时执行三项守卫，不能仅靠单测单独调用', () => {
    const sources = [...designSources(), ...sample('<script setup>el.style.padding = "40px"</script><template><el-new-control/></template><style>* {all:unset}</style>')]
    const violations = auditDesignContracts(sources).join('\n')
    expect(violations).toContain('禁止使用 all')
    expect(violations).toContain('未授权运行时样式')
    expect(violations).toContain('尚未登记样式归属')
  })
})

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

describe('按钮与菜单的样式归属', () => {
  it.each([
    '.action { font-size: var(--app-font-size-body); }',
    ':deep(.el-button) { font: inherit; }',
    ':global(.external .el-button) { padding-inline: 20px; }',
    '.action:is(:hover, :focus) { min-height: 50px; }',
    'button { line-height: var(--app-line-height-body); }',
    '.action { --app-button-font-size: var(--app-font-size-body); }',
  ])('合法 token 也不能绕过按钮的属性归属：%s', css => {
    for (const tag of ['el-button', 'ElButton']) {
      expect(auditSharedStyles(sample(`<template><${tag} class="action"/></template><style scoped>${css}</style>`)), tag).not.toEqual([])
    }
  })

  it.each([
    'style="padding: 20px"',
    ':style="{ fontSize: size }"',
    ':style="{ paddingInline: spacing }"',
    ':style="{ ...styles }"',
    ':style="styles"',
    'v-bind="attrs"',
  ])('拒绝按钮内联或不可确认的覆盖：%s', binding => {
    expect(auditSharedStyles(sample(`<template><el-button ${binding}/></template>`))).not.toEqual([])
  })

  it('跨文件 CSS、无本地实例的 deep/global 和菜单标签同样受保护', () => {
    expect(auditSharedStyles([
      ...sample('<template><el-button class="action"/></template>'),
      { file: 'styles/private.css', source: '.action { font-size: var(--app-font-size-body); }' },
    ])).not.toEqual([])
    for (const css of [
      ':deep(.el-button) { font-size: var(--app-font-size-body); }',
      ':global(.app-row-actions-menu__label) { font-size: var(--app-font-size-body); }',
      '.app-row-actions { font-weight: var(--app-font-weight-strong); }',
    ]) expect(auditSharedStyles(sample(`<template><div/></template><style>${css}</style>`))).not.toEqual([])
  })

  it('真实回归：菜单不能在共享组件内部把 small 覆盖为正文字号', () => {
    const source = readFileSync(resolve('src/components/AppRowActions.vue'), 'utf8')
    const broken = source.replace('text-align: left;', 'font-size: var(--app-font-size-body);\n  text-align: left;')
    expect(auditSharedStyles(sample(source, 'components/AppRowActions.vue'))).toEqual([])
    expect(auditSharedStyles(sample(broken, 'components/AppRowActions.vue'))).not.toEqual([])
  })

  it('图标与关闭入口的消费方只能使用尺寸属性', () => {
    for (const tag of ['AppIconButton', 'app-icon-button', 'AppCloseButton']) {
      expect(auditSharedStyles(sample(`<template><${tag} class="tool" label="刷新" size="sm"/></template>`))).toEqual([])
      expect(auditSharedStyles(sample(`<template><${tag} class="tool"/></template><style>.tool { height: 50px; }</style>`))).not.toEqual([])
    }
  })

  it('允许布局、独立复合内容与装饰伪元素，避免误伤子文字', () => {
    for (const css of [
      '.action { margin-left: auto; align-self: center; }',
      '.action::after { height: 2px; }',
      ':global(.grid .el-button > span > b) { font-size: var(--app-font-size-body); }',
      '.action :deep(.el-icon) { font-size: var(--app-icon-size-sm); }',
    ]) expect(auditSharedStyles(sample(`<template><el-button class="action"/></template><style scoped>${css}</style>`)), css).toEqual([])
    expect(auditSharedStyles(sample('<template><el-button class="action" :class="{ \'is-active\': active }"/><span class="other is-active"/></template><style>.other.is-active { font-size: var(--app-font-size-body); }</style>'))).toEqual([])
    expect(auditSharedStyles(sample('<template><el-button size="small"/><el-button class="app-button-badge"/></template>'))).toEqual([])
  })

  it('持有者精确到文件、选择器、属性与理由，禁止整文件放行并清理失效登记', () => {
    const role = {
      className: 'el-button', properties: ['font-size', 'padding'],
      owners: [{ file: 'styles/global.css', selectors: ['.el-button'], properties: ['font-size'], reason: '共享按钮字号' }],
    }
    const sources = [{ file: 'styles/global.css', source: '.el-button { font-size: var(--app-font-size-caption); }' }]
    const verify = { verifyOwners: true }
    expect(auditSharedStyles(sources, [role], verify)).toEqual([])
    expect(auditSharedStyles([{ ...sources[0], source: `${sources[0].source}\n.extra.el-button { font-size: inherit; }` }], [role], verify)).not.toEqual([])
    expect(auditSharedStyles([{ ...sources[0], source: '.el-button { padding: 20px; }' }], [role], verify)).not.toEqual([])
    expect(auditSharedStyles(sources, [{ ...role, owners: [{ ...role.owners[0], reason: '' }] }], verify)).not.toEqual([])
    expect(auditSharedStyles(sources, [{ ...role, owners: [{ ...role.owners[0], properties: ['font-size', 'padding'] }] }], verify)).not.toEqual([])
    expect(auditSharedStyles([], [role], verify)).not.toEqual([])
  })
})

describe('全部基础控件的样式归属接入', () => {
  it.each([
    'el-input', 'ElInputNumber', 'AppSearchInput', 'AppSelect', 'AppFilterSelect',
    'AppMultiSelect', 'IndicatorSelect', 'AppDatePicker', 'TradeDatePicker',
    'PageSegmented', 'el-radio-button', 'el-checkbox-button', 'el-switch',
    'el-checkbox', 'el-radio', 'AppForm', 'el-form-item', 'AppDataTable',
    'AppPagination', 'AppDialog', 'PageDrawer', 'AppDetailDrawer', 'PageSettingsDrawer',
    'el-card', 'AppTableCard', 'el-tabs', 'el-popover',
  ])('%s 的消费方只能选择角色，不能重写字号', tag => {
    const source = `<template><${tag} class="probe"/></template><style scoped>.probe { font-size: var(--app-font-size-body); }</style>`
    expect(auditSharedStyles(sample(source)), tag).not.toEqual([])
    expect(auditSharedStyles(sample(`<template><${tag} class="probe"/></template><style>.probe { margin-left: auto; }</style>`)), tag).toEqual([])
  })

  it.each([
    '.el-select__wrapper { min-height: 80px; }',
    ':deep(.el-input__inner) { line-height: var(--app-line-height-caption); }',
    ':global(.el-select-dropdown__item) { padding: 40px; }',
    '.el-form-item__label { font-weight: var(--app-font-weight-strong); }',
    '.el-dialog__body { padding: 0; }',
    '.page-drawer-surface__header { padding: 0; }',
    '.el-card__body { padding: 0; }',
    '.app-drawer-title { font-size: var(--app-font-size-page-title); }',
    '.el-tabs__content { min-height: 80px; }',
    '.el-checkbox { height: 10px; }',
    '.el-radio-button__inner { --app-choice-control-height: 80px; }',
  ])('内层、候选项和共享变量也不能绕过：%s', css => {
    expect(auditSharedStyles(sample(`<template><div/></template><style>${css}</style>`))).not.toEqual([])
  })

  it('表格 cell 追踪所属表格及其祖先，保留独立指标条的同名类', () => {
    const table = '<template><div class="audit"><AppDataTable/></div></template>'
    expect(auditSharedStyles(sample(`${table}<style scoped>.audit :deep(.cell) { font-size: var(--app-font-size-caption); }</style>`))).not.toEqual([])
    expect(auditSharedStyles(sample('<template><div class="cell"/></template><style scoped>.cell { font-size: var(--app-font-size-caption); }</style>'))).toEqual([])
    expect(auditSharedStyles([{ file: 'styles/private.css', source: '.el-table .cell { font-size: var(--app-font-size-caption); }' }])).not.toEqual([])
  })

  it('原生内层元素选择器沿共享控件别名归属，独立原生表单不被误伤', () => {
    expect(auditSharedStyles(sample('<template><el-input class="formula" type="textarea"/></template><style>:global(.formula textarea) { font-family: var(--app-font-family-mono); }</style>'))).not.toEqual([])
    expect(auditSharedStyles(sample('<template><AppSelect class="select"/></template><style>.select input { font-size: var(--app-font-size-caption); }</style>'))).not.toEqual([])
    expect(auditSharedStyles(sample('<template><label class="login"><input/></label></template><style>.login input { font-size: var(--app-font-size-body); }</style>'))).toEqual([])
  })

  it('底层适配器可精确转发 attrs，复制到普通消费方或增加样式绑定仍失败', () => {
    const source = '<template><el-select v-bind="$attrs"/></template>'
    expect(auditSharedStyles(sample(source, 'components/AppSelect.vue'))).toEqual([])
    expect(auditSharedStyles(sample(source, 'views/AppSelect.vue'))).not.toEqual([])
    expect(auditSharedStyles(sample(source.replace('/>', ':style="styles"/>'), 'components/AppSelect.vue'))).not.toEqual([])
    expect(auditSharedStyles(sample('<template><AppSelect v-bind="$attrs"/></template>'))).not.toEqual([])
  })

  it.each([
    '<el-card :body-style="{ padding: \'0\' }"/>',
    '<AppDataTable :cell-style="{ fontSize: size }"/>',
    '<el-popover :popper-style="{ padding: \'0\' }"/>',
    '<AppSelect :style="{ fontSize }"/>',
    '<AppSelect :style="{ [property]: value }"/>',
  ])('库组件的样式属性入口同样接受检查：%s', control => {
    expect(auditSharedStyles(sample(`<template>${control}</template>`))).not.toEqual([])
  })

  it('每个基础家族均登记持有者，已有共享实现不保留第二套选择器尺寸配方', () => {
    for (const name of ['el-input', 'el-select', 'el-date-editor', 'page-segmented', 'el-checkbox', 'el-form', 'el-table', 'el-pagination', 'el-dialog', 'el-drawer', 'el-card', 'el-card__body', 'el-tabs', 'el-popper', 'cell']) {
      const role = designContracts.styleRoles.find(role => role.className === name)
      expect(role?.owners?.length, name).toBeGreaterThan(0)
    }
    const select = readFileSync(resolve('src/components/AppSelect.vue'), 'utf8')
    expect(auditSharedStyles(sample(select, 'components/AppSelect.vue'))).toEqual([])
    expect(auditSharedStyles(sample(select.replace('padding-block: 0;', 'font-size: var(--app-font-size-caption); padding-block: 0;'), 'components/AppSelect.vue'))).not.toEqual([])
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


describe('按钮导航与命令角色', () => {
  it('命令不因追求无底外观误用链接，导航必须显式声明意图', () => {
    expect(auditButtonKinds(sample('<template><el-button link @click="retry">重试</el-button></template>'))).toHaveLength(1)
    expect(auditButtonKinds(sample('<template><ElButton link @click="retry">重试</ElButton></template>'))).toHaveLength(1)
    expect(auditButtonKinds(sample('<template><el-button data-button-kind="navigation" text>返回</el-button></template>'))).toHaveLength(1)
    expect(auditButtonKinds(sample('<template><el-button data-button-kind="navigation" link>返回</el-button><el-button text>重试</el-button></template>'))).toEqual([])
  })
  it('动态链接样式仅由共享行操作按显式动作角色渲染，近似路径不放行', () => {
    const source = `<template><el-button :link="action.kind === 'navigation'"
      :text="action.kind !== 'navigation'" :data-button-kind="action.kind ?? 'command'" /></template>`
    expect(auditButtonKinds(sample(source, 'components/AppRowActions.vue'))).toEqual([])
    expect(auditButtonKinds(sample(source, 'views/AppRowActions.vue'))).toHaveLength(1)
    expect(auditButtonKinds(sample(source.replace(":text=\"action.kind !== 'navigation'\"", 'text'), 'components/AppRowActions.vue'))).toHaveLength(1)
    expect(auditButtonKinds(sample(source.replace(":text=\"action.kind !== 'navigation'\"", ''), 'components/AppRowActions.vue'))).toHaveLength(1)
    expect(auditButtonKinds(sample('<template><el-button data-button-kind="navigation" :link="enabled" /></template>'))).toHaveLength(1)
  })
})


describe('透明命令与持久状态的边界', () => {
  const css = readFileSync(resolve('src/styles/buttonStates.css'), 'utf8')
  it('真实状态配方通过；文字底色、菜单隔离、图标反馈和持久状态退化会被拦截', () => {
    expect(auditButtonStates(css)).toEqual([])
    for (const broken of [
      css.replace('is-text:not(.is-has-bg, .app-row-actions-menu__item,', 'is-text:not(.is-has-bg,'),
      css.replace('--app-button-hover-bg: var(--app-icon-hover-bg)', '--app-button-hover-bg: transparent'),
      css.replace('--app-button-rest-bg: var(--app-interaction-selected-background)', '--app-button-rest-bg: transparent'),
    ]) expect(auditButtonStates(broken)).not.toEqual([])
  })
  it.each([
    ['中性悬浮不能重新混入正文色', '--app-button-hover-text: var(--app-button-tone);', '--app-button-hover-text: color-mix(in srgb, var(--app-button-tone) 85%, var(--el-text-color-primary));'],
    ['按下不能退回无变化或大幅泛白', '--app-button-pressed-text: color-mix(in srgb, var(--app-button-tone) 80%, var(--app-button-text-state-target));', '--app-button-pressed-text: var(--app-button-tone);'],
    ['语义悬浮不能退回原色', '--app-button-hover-text: color-mix(in srgb, var(--app-button-tone) 88%, var(--app-button-text-state-target));', '--app-button-hover-text: var(--app-button-tone);'],
    ['白天必须加深', '--app-button-text-state-target: var(--el-color-black);', '--app-button-text-state-target: var(--el-color-white);'],
    ['夜间必须提亮', '--app-button-text-state-target: var(--el-color-white);', '--app-button-text-state-target: var(--el-color-black);'],
    ['语义状态必须保留危险色', '.el-button--warning, .el-button--danger, .is-tone-primary,', '.el-button--warning, .is-tone-primary,'],
    ['语义悬浮不能误伤带底色按钮', '.is-tone-warning, .is-tone-danger):not(.is-has-bg,', '.is-tone-warning, .is-tone-danger):not('],
  ])('%s', (_name, before, after) => {
    expect(css).toContain(before)
    expect(auditButtonStates(css.replaceAll(before, after))).not.toEqual([])
  })
})
