<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getHealth, type HealthData } from '@/api/health'

const health = ref<HealthData | null>(null)
const loading = ref(false)
const error = ref('')

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    health.value = await getHealth()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <div class="home v-page">
    <div class="v-scroll">
      <div class="home-inner">
    <el-card shadow="never" v-loading="loading">
      <template #header>
        <div class="header">
          <span>A股趋势龙头选股、打分与回测系统</span>
          <el-button :loading="loading" size="small" @click="refresh">刷新自检</el-button>
        </div>
      </template>

      <el-alert
        v-if="error"
        :title="`后端连接失败：${error}`"
        type="error"
        :closable="false"
      />

      <el-descriptions v-else-if="health" :column="1" border>
        <el-descriptions-item label="服务状态">
          <el-tag :type="health.status === 'up' ? 'success' : 'danger'">
            {{ health.status }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="DuckDB">
          <el-tag :type="health.duckdb_ok ? 'success' : 'danger'">
            {{ health.duckdb_ok ? '已连通' : '未连通' }}
          </el-tag>
          <span class="detail">{{ health.duckdb }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="历史深度">近 {{ health.history_years }} 年</el-descriptions-item>
        <el-descriptions-item label="主基准">{{ health.benchmark_main }}（中证500）</el-descriptions-item>
        <el-descriptions-item label="榜单 Top N">{{ health.top_n }}</el-descriptions-item>
      </el-descriptions>

      <el-empty v-else description="暂无自检数据" />

      <p class="note">M0 脚手架已就绪。后续里程碑将逐步上线榜单 / 个股 / 筛选 / 回测页面。</p>
    </el-card>
      </div>
    </div>
  </div>
</template>

<style scoped>
.home-inner {
  max-width: 720px;
  margin: 0 auto;
  padding: 24px 0;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
}
.detail {
  margin-left: 8px;
  color: #909399;
  font-size: 12px;
}
.note {
  margin-top: 16px;
  color: #909399;
  font-size: 13px;
}
</style>
