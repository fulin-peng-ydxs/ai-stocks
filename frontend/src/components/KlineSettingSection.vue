<script setup lang="ts">
// 抽屉内的「K 线范围」配置：编辑全局快捷范围选项与默认范围，所有看 K 线的页面同步生效。
import { ref, watch } from 'vue'
import PageSettingItem from '@/components/PageSettingItem.vue'
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
  <div class="kline-setting-fields" data-testid="kline-setting-section">
    <PageSettingItem label="快捷范围" hint="按交易日填写，多个范围用逗号分隔，如 15,30,60。">
      <el-input v-model="periodsStr" placeholder="15,30,60" @blur="commitPeriods" @keyup.enter="commitPeriods" />
    </PageSettingItem>
    <PageSettingItem label="提供「全部」选项" layout="inline">
      <el-switch v-model="prefs.includeAll" />
    </PageSettingItem>
    <PageSettingItem label="默认范围" layout="inline">
      <el-select v-model="prefs.defaultPeriod" style="width: 130px">
        <el-option v-for="o in options" :key="o.value" :value="o.value" :label="o.label" />
      </el-select>
    </PageSettingItem>
  </div>
</template>
