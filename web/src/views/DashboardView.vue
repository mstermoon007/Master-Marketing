<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { callApi } from '../api/client'
import PageHeader from '../components/PageHeader.vue'
import { useWorkspaceStore } from '../stores/workspace'
import type { WorkspaceOverview } from '../api/types'

const ws = useWorkspaceStore()
const data = ref<WorkspaceOverview | null>(null)
const loading = ref(false)

async function load() {
  if (!ws.currentWorkspaceId) return
  loading.value = true
  try {
    ws.loadDepartments().catch(() => undefined)
    data.value = await callApi<WorkspaceOverview>('getWorkspaceOverview', {
      workspaceId: ws.currentWorkspaceId,
    })
  } catch (e: any) {
    ElMessage.error(e?.message || '工作台加载失败')
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

watch(() => ws.currentWorkspaceId, load)
</script>

<template>
  <div class="page">
    <PageHeader
      title="工作台"
      :description="data ? `${data.workspace.name} · ${data.today}` : '空间与团队今日填报概览'"
    />

    <div v-loading="loading">
      <el-row :gutter="16" class="page-card">
        <el-col :span="6">
          <el-card shadow="never">
            <div class="stat-label">今日提交率</div>
            <div class="stat-value">{{ data?.todayRateText || '—' }}</div>
            <div class="stat-sub">
              已提交 {{ data?.todaySubmitted ?? 0 }} / 应提交 {{ data?.todayExpected ?? 0 }}
            </div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="never">
            <div class="stat-label">未提交人次</div>
            <div class="stat-value">{{ data?.missingCount ?? 0 }}</div>
            <div class="stat-sub">今日尚未提交的成员人次</div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="never">
            <div class="stat-label">进行中任务</div>
            <div class="stat-value">{{ data?.activeTaskCount ?? 0 }}</div>
            <div class="stat-sub">当前生效的填报任务</div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="never">
            <div class="stat-label">近 7 天异常</div>
            <div class="stat-value">{{ data?.anomalyCount ?? 0 }}</div>
            <div class="stat-sub">预警与严重级别发现</div>
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="16">
        <el-col :span="10">
          <el-card shadow="never" header="近 7 天提交趋势">
            <el-table :data="data?.trend || []" size="small">
              <el-table-column prop="date" label="日期" min-width="110" />
              <el-table-column label="提交率" min-width="120">
                <template #default="{ row }">
                  <el-progress
                    :percentage="row.rate === null ? 0 : Math.round(row.rate * 100)"
                    :format="() => row.rateText"
                  />
                </template>
              </el-table-column>
              <el-table-column label="提交 / 应提交" min-width="120">
                <template #default="{ row }">
                  {{ row.submittedCount }} / {{ row.expectedCount }}
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-col>

        <el-col :span="14">
          <el-card shadow="never" header="团队今日进度">
            <el-table :data="data?.teams || []" size="small" empty-text="暂无团队">
              <el-table-column prop="name" label="团队" min-width="140" />
              <el-table-column label="部门" min-width="120">
                <template #default="{ row }">
                  {{ ws.departmentName(row.department_id) || '—' }}
                </template>
              </el-table-column>
              <el-table-column label="提交率" min-width="140">
                <template #default="{ row }">
                  <el-progress
                    :percentage="row.rate === null ? 0 : Math.round(row.rate * 100)"
                    :format="() => row.rateText"
                  />
                </template>
              </el-table-column>
              <el-table-column label="提交 / 应提交" min-width="110">
                <template #default="{ row }">
                  {{ row.submittedCount }} / {{ row.expectedCount }}
                </template>
              </el-table-column>
            </el-table>
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
  font-size: 28px;
  font-weight: 600;
}

.stat-sub {
  margin-top: 6px;
  font-size: 12px;
  color: #8a94a6;
}
</style>
