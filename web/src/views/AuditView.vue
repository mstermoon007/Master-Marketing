<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { callApi } from '../api/client'
import PageHeader from '../components/PageHeader.vue'
import { useWorkspaceStore } from '../stores/workspace'
import type { AuditPage, AuditRow } from '../api/types'
import { daysAgo, formatDateTime, today } from '../utils/date'

const ws = useWorkspaceStore()
const rows = ref<AuditRow[]>([])
const total = ref(0)
const page = ref(0)
const pageSize = ref(20)
const loading = ref(false)

const filters = reactive({
  range: [daysAgo(6), today()] as string[],
  actor: '',
  action: '',
})

async function load() {
  if (!ws.currentWorkspaceId) return
  loading.value = true
  try {
    const data = await callApi<AuditPage>('listAuditLogs', {
      workspaceId: ws.currentWorkspaceId,
      from: filters.range?.[0] || undefined,
      to: filters.range?.[1] || undefined,
      actor: filters.actor.trim() || undefined,
      action: filters.action.trim() || undefined,
      page: page.value,
      pageSize: pageSize.value,
    })
    rows.value = data.items
    total.value = data.total
  } catch (e: any) {
    ElMessage.error(e?.message || '审计日志加载失败')
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

watch(() => ws.currentWorkspaceId, () => {
  page.value = 0
  load()
})

function search() {
  page.value = 0
  load()
}

function onPageChange(value: number) {
  page.value = value - 1
  load()
}

function detailText(detail: unknown): string {
  if (!detail) return ''
  try {
    return typeof detail === 'string' ? detail : JSON.stringify(detail)
  } catch {
    return ''
  }
}
</script>

<template>
  <div class="page">
    <PageHeader title="操作审计" description="空间内的管理操作与登录记录">
      <el-button :loading="loading" @click="search">刷新</el-button>
    </PageHeader>

    <el-card shadow="never">
      <div class="toolbar">
        <el-date-picker
          v-model="filters.range"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
        />
        <el-input v-model="filters.actor" placeholder="操作人 UID" style="width: 200px" clearable />
        <el-input v-model="filters.action" placeholder="动作，如 template_publish" style="width: 220px" clearable />
        <el-button type="primary" @click="search">查询</el-button>
      </div>

      <el-table :data="rows" v-loading="loading" size="small" empty-text="暂无审计记录">
        <el-table-column label="时间" min-width="170">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="actor" label="操作人" min-width="170" show-overflow-tooltip />
        <el-table-column prop="action" label="动作" min-width="150" />
        <el-table-column prop="target_type" label="对象" min-width="130" />
        <el-table-column prop="target_id" label="对象 ID" min-width="140" show-overflow-tooltip />
        <el-table-column label="详情" min-width="220">
          <template #default="{ row }">
            <span class="muted">{{ detailText(row.detail) }}</span>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          layout="total, prev, pager, next"
          :total="total"
          :page-size="pageSize"
          :current-page="page + 1"
          @current-change="onPageChange"
        />
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}
</style>
