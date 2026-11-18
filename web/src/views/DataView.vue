<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { callApi } from '../api/client'
import PageHeader from '../components/PageHeader.vue'
import ExportButton from '../components/ExportButton.vue'
import { useWorkspaceStore } from '../stores/workspace'
import type { EntryRow, TemplateRow } from '../api/types'
import { daysAgo, today } from '../utils/date'

const ws = useWorkspaceStore()
const entries = ref<EntryRow[]>([])
const templates = ref<TemplateRow[]>([])
const loading = ref(false)
const page = ref(0)
const pageSize = 100

const filters = reactive({
  range: [daysAgo(6), today()] as string[],
  templateId: '',
})

const memberNames = computed(() => {
  const map: Record<string, string> = {}
  ws.members.forEach((m) => {
    map[m.user_id] = m.name
  })
  return map
})

const fieldColumns = computed(() => {
  if (!filters.templateId) return []
  const matched = templates.value
    .filter((t) => t.template_id === filters.templateId && t.status === 'published')
    .sort((a, b) => b.version - a.version)
  return matched[0]?.fields || []
})

const exportPayload = computed(() => ({
  teamId: ws.currentTeamId,
  startDate: filters.range[0],
  endDate: filters.range[1],
  templateId: filters.templateId || undefined,
}))

const exportName = computed(
  () => `entries_${ws.currentTeamId}_${filters.range[0]}_${filters.range[1]}.xlsx`,
)

function valuesOf(entry: EntryRow): Record<string, unknown> {
  const first = (entry.form_data || [])[0]
  return first?.values || {}
}

function valueText(entry: EntryRow, key: string): string {
  const value = valuesOf(entry)[key]
  if (Array.isArray(value)) return value.join('、')
  return value === undefined || value === null ? '' : String(value)
}

function statusText(status: string): string {
  return status === 'submitted' ? '已提交' : status === 'draft' ? '草稿' : status
}

async function loadTemplates() {
  if (!ws.currentTeamId) {
    templates.value = []
    return
  }
  try {
    templates.value = await callApi<TemplateRow[]>('listTemplates', { teamId: ws.currentTeamId })
  } catch {
    templates.value = []
  }
}

async function load() {
  if (!ws.currentTeamId || !filters.range?.length) return
  loading.value = true
  try {
    entries.value = await callApi<EntryRow[]>('listTeamEntries', {
      teamId: ws.currentTeamId,
      from: filters.range[0],
      to: filters.range[1],
      page: page.value,
      pageSize,
    })
  } catch (e: any) {
    ElMessage.error(e?.message || '数据加载失败')
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
  await ws.loadMembers().catch(() => undefined)
  await loadTemplates()
  await load()
})

watch(() => ws.currentTeamId, async () => {
  page.value = 0
  filters.templateId = ''
  await ws.loadMembers().catch(() => undefined)
  await loadTemplates()
  await load()
})

function search() {
  page.value = 0
  load()
}

function prevPage() {
  if (page.value === 0) return
  page.value -= 1
  load()
}

function nextPage() {
  if (entries.value.length < pageSize) return
  page.value += 1
  load()
}
</script>

<template>
  <div class="page">
    <PageHeader title="数据中心" description="按团队、日期与模板筛选日报">
      <ExportButton
        :payload="exportPayload"
        :filename="exportName"
        :disabled="!ws.currentTeamId || !filters.range?.length"
      />
    </PageHeader>

    <el-card shadow="never" class="page-card">
      <div class="toolbar">
        <el-date-picker
          v-model="filters.range"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          :clearable="false"
        />
        <el-select v-model="filters.templateId" clearable placeholder="全部模板" style="width: 200px">
          <el-option
            v-for="tpl in templates.filter((t) => t.status === 'published')"
            :key="tpl.id"
            :label="`${tpl.name} v${tpl.version}`"
            :value="tpl.template_id"
          />
        </el-select>
        <el-button type="primary" @click="search">查询</el-button>
      </div>

      <el-table :data="entries" v-loading="loading" size="small" empty-text="暂无数据">
        <el-table-column prop="entry_date" label="日期" width="110" />
        <el-table-column label="成员" min-width="120">
          <template #default="{ row }">
            {{ memberNames[row.user_id] || row.user_id }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 'submitted' ? 'success' : 'info'">
              {{ statusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column
          v-for="field in fieldColumns"
          :key="field.fieldKey"
          :label="field.label || field.fieldKey"
          min-width="120"
        >
          <template #default="{ row }">
            {{ valueText(row, field.fieldKey) }}
          </template>
        </el-table-column>
        <el-table-column v-if="!fieldColumns.length" label="表单数据" min-width="260">
          <template #default="{ row }">
            <span class="muted">{{ JSON.stringify(valuesOf(row)) }}</span>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-button size="small" :disabled="page === 0" @click="prevPage">上一页</el-button>
        <span class="muted">第 {{ page + 1 }} 页 · 每页 {{ pageSize }} 条</span>
        <el-button size="small" :disabled="entries.length < pageSize" @click="nextPage">下一页</el-button>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.pager {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 14px;
}
</style>
