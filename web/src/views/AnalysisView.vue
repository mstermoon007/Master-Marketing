<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { callApi } from '../api/client'
import PageHeader from '../components/PageHeader.vue'
import { useWorkspaceStore } from '../stores/workspace'
import type { AnalysisOverview, AnalysisTaskView } from '../api/types'

const ws = useWorkspaceStore()
const overview = ref<AnalysisOverview | null>(null)
const detail = ref<AnalysisTaskView | null>(null)
const loading = ref(false)

async function load() {
  if (!ws.currentTeamId) {
    overview.value = null
    detail.value = null
    return
  }
  loading.value = true
  try {
    overview.value = await callApi<AnalysisOverview>('getAnalysisOverview', {
      teamId: ws.currentTeamId,
    })
    detail.value = overview.value.latest
  } catch (e: any) {
    ElMessage.error(e?.message || '分析数据加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  if (!ws.spaces.length) {
    try {
      await ws.loadSpaces()
    } catch {
      return
    }
  }
  await load()
})

watch(() => ws.currentTeamId, load)

async function openTask(id: string) {
  try {
    detail.value = await callApi<AnalysisTaskView>('getAnalysisTask', { id })
  } catch (e: any) {
    ElMessage.error(e?.message || '分析结果加载失败')
  }
}

function levelType(level: string): string {
  return level === 'critical' ? 'danger' : level === 'warning' ? 'warning' : 'info'
}
</script>

<template>
  <div class="page">
    <PageHeader title="分析结果" description="规则执行结果与异常发现（只读）" />

    <div v-loading="loading">
      <el-row :gutter="16" class="page-card">
        <el-col :span="8">
          <el-card shadow="never">
            <div class="stat-label">分析任务</div>
            <div class="stat-value">{{ overview?.taskCount ?? 0 }}</div>
          </el-card>
        </el-col>
        <el-col :span="8">
          <el-card shadow="never">
            <div class="stat-label">发现总数</div>
            <div class="stat-value">{{ overview?.findingCount ?? 0 }}</div>
          </el-card>
        </el-col>
        <el-col :span="8">
          <el-card shadow="never">
            <div class="stat-label">最近执行</div>
            <div class="stat-value small">
              {{ overview?.latest ? `${overview.latest.task.from} ~ ${overview.latest.task.to}` : '暂无' }}
            </div>
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="16">
        <el-col :span="9">
          <el-card shadow="never" header="分析任务">
            <el-table :data="overview?.tasks || []" size="small" empty-text="暂无分析任务">
              <el-table-column prop="from" label="开始" min-width="100" />
              <el-table-column prop="to" label="结束" min-width="100" />
              <el-table-column prop="statusText" label="状态" width="90" />
              <el-table-column label="操作" width="80">
                <template #default="{ row }">
                  <el-button link type="primary" @click="openTask(row.id)">查看</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-col>

        <el-col :span="15">
          <el-card shadow="never">
            <template #header>
              <span>发现明细</span>
              <span v-if="detail" class="muted detail-sub">
                {{ detail.task.from }} ~ {{ detail.task.to }} · {{ detail.task.statusText }}
              </span>
            </template>

            <el-table :data="detail?.findings || []" size="small" empty-text="暂无异常发现">
              <el-table-column prop="levelText" label="级别" width="90">
                <template #default="{ row }">
                  <el-tag :type="levelType(row.level)" size="small">{{ row.levelText }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="title" label="发现" min-width="200" />
              <el-table-column prop="findingCode" label="编码" min-width="130" />
              <el-table-column prop="ruleCode" label="规则" min-width="130" />
            </el-table>

            <div v-if="detail?.result?.reportText" class="report">
              <div class="report-title">分析报告</div>
              <pre class="report-text">{{ detail.result.reportText }}</pre>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </div>
  </div>
</template>

<style scoped>
.stat-label {
  font-size: 13px;
  color: #8a94a6;
}

.stat-value {
  margin-top: 8px;
  font-size: 26px;
  font-weight: 600;
}

.stat-value.small {
  font-size: 16px;
  font-weight: 500;
}

.detail-sub {
  margin-left: 12px;
  font-size: 12px;
}

.report {
  margin-top: 16px;
}

.report-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 8px;
}

.report-text {
  margin: 0;
  padding: 12px;
  background: #f7f9fc;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
