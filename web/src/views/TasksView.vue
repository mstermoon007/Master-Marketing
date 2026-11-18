<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { callApi } from '../api/client'
import PageHeader from '../components/PageHeader.vue'
import { useWorkspaceStore } from '../stores/workspace'
import type { ReportTaskRow, TemplateRow } from '../api/types'
import { today } from '../utils/date'

const ws = useWorkspaceStore()
const tasks = ref<ReportTaskRow[]>([])
const templates = ref<TemplateRow[]>([])
const loading = ref(false)
const saving = ref(false)
const statusFilter = ref('active')

const dialog = reactive({
  visible: false,
  title: '',
  templateId: '',
  startDate: today(),
  endDate: '',
  dueTime: '',
  workdaysOnly: false,
})

function publishedTemplates(): TemplateRow[] {
  const latest: Record<string, TemplateRow> = {}
  templates.value
    .filter((t) => t.status === 'published')
    .forEach((t) => {
      if (!latest[t.template_id] || t.version > latest[t.template_id].version) {
        latest[t.template_id] = t
      }
    })
  return Object.values(latest)
}

async function load() {
  if (!ws.currentTeamId) {
    tasks.value = []
    return
  }
  loading.value = true
  try {
    const [list, tpls] = await Promise.all([
      callApi<ReportTaskRow[]>('listReportTasks', {
        teamId: ws.currentTeamId,
        status: statusFilter.value || undefined,
      }),
      callApi<TemplateRow[]>('listTemplates', { teamId: ws.currentTeamId }),
    ])
    tasks.value = list
    templates.value = tpls
  } catch (e: any) {
    ElMessage.error(e?.message || '任务加载失败')
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
watch(statusFilter, load)

function openCreate() {
  dialog.title = ''
  dialog.templateId = ''
  dialog.startDate = today()
  dialog.endDate = ''
  dialog.dueTime = ''
  dialog.workdaysOnly = false
  dialog.visible = true
}

async function saveTask() {
  if (!dialog.title.trim()) {
    ElMessage.warning('请填写任务名称')
    return
  }
  const tpl = publishedTemplates().find((t) => t.template_id === dialog.templateId)
  if (!tpl) {
    ElMessage.warning('请选择已发布模板')
    return
  }
  saving.value = true
  try {
    await callApi('createReportTask', {
      teamId: ws.currentTeamId,
      payload: {
        title: dialog.title.trim(),
        template_id: tpl.template_id,
        template_version: tpl.version,
        start_date: dialog.startDate,
        end_date: dialog.endDate || null,
        due_time: dialog.dueTime || null,
        workdays_only: dialog.workdaysOnly,
        scope: { type: 'all' },
      },
    })
    dialog.visible = false
    ElMessage.success('任务已创建')
    await load()
  } catch (e: any) {
    ElMessage.error(e?.message || '创建失败')
  } finally {
    saving.value = false
  }
}

async function closeTask(row: ReportTaskRow) {
  try {
    await ElMessageBox.confirm(`关闭任务「${row.title}」？`, '关闭任务', { type: 'warning' })
  } catch {
    return
  }
  try {
    await callApi('closeReportTask', { id: row.id })
    ElMessage.success('任务已关闭')
    await load()
  } catch (e: any) {
    ElMessage.error(e?.message || '关闭失败')
  }
}
</script>

<template>
  <div class="page">
    <PageHeader title="填报任务" description="任务决定谁、哪天、何时前填写">
      <el-button type="primary" @click="openCreate">新建任务</el-button>
    </PageHeader>

    <el-card shadow="never">
      <div class="toolbar">
        <el-radio-group v-model="statusFilter">
          <el-radio-button label="active">进行中</el-radio-button>
          <el-radio-button label="closed">已关闭</el-radio-button>
          <el-radio-button label="">全部</el-radio-button>
        </el-radio-group>
      </div>

      <el-table :data="tasks" v-loading="loading" size="small" empty-text="暂无任务">
        <el-table-column prop="title" label="任务名称" min-width="160" />
        <el-table-column prop="templateName" label="模板" min-width="140" />
        <el-table-column prop="dateText" label="周期" min-width="180" />
        <el-table-column prop="dueText" label="截止" width="80" />
        <el-table-column prop="scopeText" label="范围" min-width="140" />
        <el-table-column prop="statusText" label="状态" width="90" />
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'active'"
              link
              type="warning"
              @click="closeTask(row)"
            >
              关闭
            </el-button>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialog.visible" title="新建填报任务" width="520px">
      <el-form label-width="100px">
        <el-form-item label="任务名称">
          <el-input v-model="dialog.title" maxlength="128" />
        </el-form-item>
        <el-form-item label="模板">
          <el-select v-model="dialog.templateId" placeholder="选择已发布模板">
            <el-option
              v-for="tpl in publishedTemplates()"
              :key="tpl.id"
              :label="`${tpl.name} v${tpl.version}`"
              :value="tpl.template_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="开始日期">
          <el-date-picker v-model="dialog.startDate" type="date" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="结束日期">
          <el-date-picker v-model="dialog.endDate" type="date" value-format="YYYY-MM-DD" placeholder="长期" />
        </el-form-item>
        <el-form-item label="截止时间">
          <el-time-picker v-model="dialog.dueTime" value-format="HH:mm" placeholder="当天截止（可选）" />
        </el-form-item>
        <el-form-item label="仅工作日">
          <el-switch v-model="dialog.workdaysOnly" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveTask">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>
