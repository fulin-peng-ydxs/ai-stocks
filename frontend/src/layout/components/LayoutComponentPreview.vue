<script setup lang="ts">
/**
 * 组件可视化预览（P6 / M8-D）——「系统组件」库里每个组件的代表性占位预览。
 *
 * ready 使用视觉原型展示该组件种类的内容形态；loading / empty / error 直接复用
 * AppStateBlock，作为开发与验收可对照的状态规范样板。预览框固定高度，只证明规范样板
 * 的状态切换不改变容器尺寸；真实页面仍须独立接入并通过页面测试。
 */
import { computed } from 'vue'
import { Close } from '@element-plus/icons-vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
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
  <div class="cp-frame app-surface" data-testid="component-state-preview" :data-state="effState">
    <!-- 非 ready 态复用真实运行时组件，避免预览与业务页面各维护一套状态视觉。 -->
    <AppStateBlock
      v-if="effState === 'loading'"
      state="loading"
      size="compact"
      title="正在加载组件数据…"
    />
    <AppStateBlock
      v-else-if="effState === 'empty'"
      state="empty"
      size="compact"
      description="暂无组件数据"
    />
    <AppStateBlock
      v-else-if="effState === 'error'"
      state="error"
      size="compact"
      title="组件数据加载失败"
      retry
    />

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
        <div v-for="k in 3" :key="k" class="cp-card app-surface"><div class="cp-num" /><div class="cp-cap" /></div>
      </div>

      <div v-else-if="archetype === 'form'" class="cp-form">
        <div v-for="r in 3" :key="r" class="cp-fr"><span class="cp-flabel" /><span class="cp-finput" /></div>
      </div>

      <div v-else-if="archetype === 'overlay'" class="cp-overlay">
        <div class="cp-ohead"><span /><el-icon class="cp-oclose"><Close /></el-icon></div>
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

      <div v-else class="cp-structure app-surface app-surface--dashed">结构容器</div>
    </template>
  </div>
</template>

<style scoped>
.cp-frame {
  /* 四态共用 256px 稳定画布；该高度覆盖 compact 空态的完整图文，避免 overflow:hidden 裁切。 */
  box-sizing: border-box;
  height: 256px;
  padding: 12px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
/* 通用占位条：用边框色块表示内容骨架。 */
span {
  display: inline-block;
}
.cp-table {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-control-gap);
}
.cp-tr {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--app-space-2);
}
.cp-tr > span {
  height: 12px;
  background: var(--el-fill-color);
  border-radius: 3px;
}
.cp-th > span {
  height: 14px;
  background: var(--el-fill-color-dark);
  font-size: var(--app-font-size-micro);
  color: var(--el-text-color-secondary);
  text-align: left;
  padding-left: 2px;
}
.cp-list {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}
.cp-li {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
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
  gap: var(--app-space-2);
  font-size: var(--app-font-size-table);
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
  gap: var(--app-space-2);
}
.cp-input {
  height: 30px;
  flex: 1;
  border: 1px solid var(--el-border-color);
  border-radius: var(--layout-control-radius);
  background: var(--app-section-bg);
}
.cp-input.sm {
  flex: 0 0 80px;
}
.cp-btn {
  height: 30px;
  padding: 0 14px;
  display: inline-flex;
  align-items: center;
  border-radius: var(--layout-control-radius);
  background: var(--el-color-primary);
  color: var(--el-color-white);
  font-size: var(--app-font-size-caption);
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
  gap: var(--app-space-2);
}
.cp-card {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
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
  gap: var(--app-space-3);
}
.cp-fr {
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
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
  border-radius: var(--layout-control-radius);
  background: var(--app-section-bg);
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
  border-bottom: 1px solid var(--app-border-divider);
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
  gap: var(--app-space-2);
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
  gap: var(--app-space-2);
  border-top: 1px solid var(--app-border-divider);
  padding-top: 8px;
}
.cp-tabbar {
  display: flex;
  gap: var(--app-space-4);
  border-bottom: 1px solid var(--app-border-divider);
  font-size: var(--app-font-size-table);
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
  gap: var(--app-space-2);
  padding-top: 10px;
}
.cp-detail {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
}
.cp-dr {
  display: flex;
  gap: var(--app-space-3);
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
  background: var(--app-section-bg);
  border: 1px solid var(--app-border-subtle);
  border-radius: 3px;
}
.cp-master {
  flex-direction: row;
  gap: var(--app-space-2);
}
.cp-mlist {
  flex: 0 0 90px;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
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
  border-left: 1px solid var(--app-border-divider);
  padding-left: 10px;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}
.cp-structure {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-table);
}
</style>
