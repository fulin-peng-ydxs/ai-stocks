<script setup lang="ts">
// 抽屉内的「K 线范围」配置：编辑全局快捷范围选项与默认范围，所有看 K 线的页面同步生效。
import { ref, watch } from 'vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import { useKlinePrefs } from '@/composables/useKlinePrefs'

const { prefs, options, setPeriods } = useKlinePrefs()

// 用逗号分隔字符串编辑范围列表，失焦/回车时归一回写
const periodsStr = ref(prefs.periods.join(','))
watch(
  () => prefs.periods,
  (v) => {
    periodsStr.value = v.join(',')
  },
)
function commitPeriods() {
  const list = periodsStr.value
    .split(/[,，\s]+/)
    .map(Number)
    .filter((n) => n > 0 && Number.isFinite(n))
  if (list.length) setPeriods(list)
  periodsStr.value = prefs.periods.join(',')
}
</script>

<template>
  <PageSettingSection
    title="K 线范围"
    desc="快捷范围选项与默认范围，所有看 K 线的页面统一生效。"
    data-testid="kline-setting-section"
  >
    <div class="setting-item col">
      <div class="setting-label">快捷范围（交易日，逗号分隔，如 15,30,60）</div>
      <el-input v-model="periodsStr" placeholder="15,30,60" @blur="commitPeriods" @keyup.enter="commitPeriods" />
    </div>
    <div class="setting-item">
      <div class="setting-label">提供「全部」选项</div>
      <el-switch v-model="prefs.includeAll" />
    </div>
    <div class="setting-item">
      <div class="setting-label">默认范围</div>
      <el-select v-model="prefs.defaultPeriod" style="width: 130px">
        <el-option v-for="o in options" :key="o.value" :value="o.value" :label="o.label" />
      </el-select>
    </div>
  </PageSettingSection>
</template>

<style scoped>
.setting-item { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-3); padding: 6px 0; }
.setting-item.col { flex-direction: column; align-items: stretch; }
.setting-label { font-size: var(--app-font-size-table); color: var(--el-text-color-regular); }
</style>
