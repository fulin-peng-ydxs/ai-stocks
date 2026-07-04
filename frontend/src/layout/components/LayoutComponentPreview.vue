<script setup lang="ts">
/**
 * 组件可视化预览（P6 / M8-D）——「系统组件」库里每个组件的代表性占位预览。
 *
 * 不挂载真实业务组件，而是按 componentPreview.ts 的视觉原型渲染代表性 mock，并支持
 * 默认 / loading / empty / error 四态切换。预览框**固定高度**，证明「状态切换不改变外层尺寸」
 * （requirement §5.2 校验规则）。这是组件目录展示层，不引入运行时配置。
 */
import { computed } from 'vue'
import { previewArchetypeOf, FEEDBACK_DEFAULT_STATE } from '../componentPreview'
import type { ComponentKind, ComponentState } from '../schema'

const props = defineProps<{ kind: ComponentKind; state: ComponentState }>()

const archetype = computed(() => previewArchetypeOf(props.kind))

/** 实际渲染态：feedback 组件的"默认态"按种类映射为 loading/empty/error；其余默认态为 ready。 */
const effState = computed<ComponentState>(() => {
  if (props.state !== 'ready') return props.state
  return FEEDBACK_DEFAULT_STATE[props.kind] ?? 'ready'
})
</script>

<template>
  <div class="cp-frame">
    <!-- 通用状态占位：固定高度内渲染，切换不改变外层尺寸。 -->
    <div v-if="effState === 'loading'" class="cp-state">
      <el-skeleton :rows="3" animated />
    </div>
    <el-empty v-else-if="effState === 'empty'" class="app-empty app-empty--compact" description="暂无数据" />
    <div v-else-if="effState === 'error'" class="cp-state cp-error">
      <span class="cp-error-icon">⚠</span>
      <span>加载失败</span>
      <el-button size="small" text type="primary">重试</el-button>
    </div>

    <!-- 默认（ready）态：按视觉原型渲染代表性 mock。 -->
    <template v-else>
      <div v-if="archetype === 'table'" class="cp-table">
        <div class="cp-tr cp-th"><span>列 A</span><span>列 B</span><span>列 C</span><span>列 D</span></div>
        <div v-for="r in 4" :key="r" class="cp-tr"><span /><span /><span /><span /></div>
      </div>

      <div v-else-if="archetype === 'list'" class="cp-list">
        <div v-for="r in 5" :key="r" class="cp-li"><i class="cp-dot" /><span /></div>
      </div>

      <div v-else-if="archetype === 'tree'" class="cp-tree">
        <div class="cp-node l0">▸ 节点</div>
        <div class="cp-node l1">▸ 子节点</div>
        <div class="cp-node l2">· 叶子</div>
        <div class="cp-node l1">▸ 子节点</div>
      </div>

      <div v-else-if="archetype === 'controls'" class="cp-controls">
        <span class="cp-input" />
        <span class="cp-input sm" />
        <span class="cp-btn">操作</span>
      </div>

      <div v-else-if="archetype === 'chart'" class="cp-chart">
        <svg viewBox="0 0 200 80" preserveAspectRatio="none">
          <polyline points="0,60 30,40 60,50 90,20 120,35 150,15 200,30" fill="none" stroke="var(--el-color-primary)" stroke-width="2" />
          <line x1="0" y1="78" x2="200" y2="78" stroke="var(--el-border-color)" stroke-width="1" />
        </svg>
      </div>

      <div v-else-if="archetype === 'kpi'" class="cp-kpi">
        <div v-for="k in 3" :key="k" class="cp-card"><div class="cp-num" /><div class="cp-cap" /></div>
      </div>

      <div v-else-if="archetype === 'form'" class="cp-form">
        <div v-for="r in 3" :key="r" class="cp-fr"><span class="cp-flabel" /><span class="cp-finput" /></div>
      </div>

      <div v-else-if="archetype === 'overlay'" class="cp-overlay">
        <div class="cp-ohead"><span /><span class="cp-oclose">✕</span></div>
        <div class="cp-obody"><span /><span /><span class="short" /></div>
        <div class="cp-ofoot"><span class="cp-btn ghost">取消</span><span class="cp-btn">确定</span></div>
      </div>

      <div v-else-if="archetype === 'tabs'" class="cp-tabs">
        <div class="cp-tabbar"><span class="active">标签一</span><span>标签二</span><span>标签三</span></div>
        <div class="cp-tabbody"><span /><span /><span class="short" /></div>
      </div>

      <div v-else-if="archetype === 'detail'" class="cp-detail">
        <div v-for="r in 4" :key="r" class="cp-dr"><span class="cp-dk" /><span class="cp-dv" /></div>
      </div>

      <div v-else-if="archetype === 'master'" class="cp-master">
        <div class="cp-mlist"><div v-for="r in 4" :key="r" class="cp-mli" :class="{ active: r === 1 }" /></div>
        <div class="cp-mdetail"><span /><span /><span class="short" /></div>
      </div>

      <div v-else class="cp-structure">结构容器</div>
    </template>
  </div>
</template>

<style scoped>
.cp-frame {
  height: 176px;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  background: var(--el-bg-color);
  padding: 12px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.cp-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 8px;
}
.cp-error {
  align-items: center;
  color: var(--el-color-danger);
  font-size: 13px;
}
.cp-error-icon {
  font-size: 22px;
}
/* 通用占位条：用边框色块表示内容骨架。 */
span {
  display: inline-block;
}
.cp-table {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.cp-tr {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}
.cp-tr span {
  height: 12px;
  background: var(--el-fill-color);
  border-radius: 3px;
}
.cp-th span {
  height: 14px;
  background: var(--el-fill-color-dark);
  font-size: 11px;
  color: var(--el-text-color-secondary);
  text-align: left;
  padding-left: 2px;
}
.cp-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.cp-li {
  display: flex;
  align-items: center;
  gap: 8px;
}
.cp-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--el-color-primary);
  flex: none;
}
.cp-li span:not(.cp-dot) {
  flex: 1;
  height: 12px;
  background: var(--el-fill-color);
  border-radius: 3px;
}
.cp-tree {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.cp-node.l1 {
  padding-left: 18px;
}
.cp-node.l2 {
  padding-left: 36px;
  color: var(--el-text-color-secondary);
}
.cp-controls {
  display: flex;
  align-items: center;
  gap: 10px;
}
.cp-input {
  height: 30px;
  flex: 1;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  background: var(--el-fill-color-light);
}
.cp-input.sm {
  flex: 0 0 80px;
}
.cp-btn {
  height: 30px;
  padding: 0 14px;
  display: inline-flex;
  align-items: center;
  border-radius: 4px;
  background: var(--el-color-primary);
  color: #fff;
  font-size: 12px;
}
.cp-btn.ghost {
  background: transparent;
  color: var(--el-text-color-regular);
  border: 1px solid var(--el-border-color);
}
.cp-chart {
  flex: 1;
  display: flex;
}
.cp-chart svg {
  width: 100%;
  height: 100%;
}
.cp-kpi {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
.cp-card {
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.cp-num {
  height: 22px;
  background: var(--el-fill-color-dark);
  border-radius: 3px;
}
.cp-cap {
  height: 10px;
  width: 60%;
  background: var(--el-fill-color);
  border-radius: 3px;
}
.cp-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.cp-fr {
  display: flex;
  align-items: center;
  gap: 12px;
}
.cp-flabel {
  width: 64px;
  height: 12px;
  background: var(--el-fill-color);
  border-radius: 3px;
}
.cp-finput {
  flex: 1;
  height: 30px;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  background: var(--el-fill-color-light);
}
.cp-overlay,
.cp-tabs,
.cp-master {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.cp-ohead {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--el-border-color);
}
.cp-ohead span:first-child {
  width: 80px;
  height: 14px;
  background: var(--el-fill-color-dark);
  border-radius: 3px;
}
.cp-oclose {
  color: var(--el-text-color-secondary);
}
.cp-obody {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 10px 0;
}
.cp-obody span,
.cp-tabbody span,
.cp-mdetail span {
  height: 12px;
  background: var(--el-fill-color);
  border-radius: 3px;
}
.cp-obody span.short,
.cp-tabbody span.short,
.cp-mdetail span.short {
  width: 50%;
}
.cp-ofoot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  border-top: 1px solid var(--el-border-color);
  padding-top: 8px;
}
.cp-tabbar {
  display: flex;
  gap: 16px;
  border-bottom: 1px solid var(--el-border-color);
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.cp-tabbar .active {
  color: var(--el-color-primary);
  border-bottom: 2px solid var(--el-color-primary);
  padding-bottom: 6px;
}
.cp-tabbody {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-top: 10px;
}
.cp-detail {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.cp-dr {
  display: flex;
  gap: 12px;
}
.cp-dk {
  width: 72px;
  height: 12px;
  background: var(--el-fill-color);
  border-radius: 3px;
}
.cp-dv {
  flex: 1;
  height: 12px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color);
  border-radius: 3px;
}
.cp-master {
  flex-direction: row;
  gap: 10px;
}
.cp-mlist {
  flex: 0 0 90px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.cp-mli {
  height: 22px;
  background: var(--el-fill-color);
  border-radius: 3px;
}
.cp-mli.active {
  background: color-mix(in srgb, var(--el-color-primary) 30%, var(--el-fill-color));
}
.cp-mdetail {
  flex: 1;
  border-left: 1px solid var(--el-border-color);
  padding-left: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.cp-structure {
  flex: 1;
  border: 1px dashed var(--el-border-color);
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
</style>
