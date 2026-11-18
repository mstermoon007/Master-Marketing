<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { callApi } from '../api/client'
import PageHeader from '../components/PageHeader.vue'
import { useWorkspaceStore } from '../stores/workspace'
import type { TemplateRow } from '../api/types'
import { today } from '../utils/date'

const ws = useWorkspaceStore()
const rows = ref<TemplateRow[]>([])
const loading = ref(false)
const saving = ref(false)

const dialog = reactive({
  visible: false,
  id: '',
  templateId: '',
  name: '',
  version: 1,
  description: '',
  entryMode: 'single',
  effectiveFrom: '',
  fieldsText: '[]',
})

async function load() {
  if (!ws.currentTeamId) {
    rows.value = []
    return
  }
  loading.value = true
  try {
    rows.value = await callApi<TemplateRow[]>('listTemplates', { teamId: ws.currentTeamId })
  } catch (e: any) {
    ElMessage.error(e?.message || '模板加载失败')
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

function openCreate() {
  dialog.id = ''
  dialog.templateId = ''
  dialog.name = ''
  dialog.version = 1
  dialog.description = ''
  dialog.entryMode = 'single'
  dialog.effectiveFrom = today()
  dialog.fieldsText = '[]'
  dialog.visible = true
}

function openEdit(row: TemplateRow) {
  dialog.id = row.id
  dialog.templateId = row.template_id
  dialog.name = row.name
  dialog.version = row.version
  dialog.description = row.description || ''
  dialog.entryMode = row.entry_mode || 'single'
  dialog.effectiveFrom = row.effective_from || ''
  dialog.fieldsText = JSON.stringify(row.fields || [], null, 2)
  dialog.visible = true
}

async function openNewVersion(row: TemplateRow) {
  try {
    const version = await callApi<number>('nextVersion', {
      teamId: ws.currentTeamId,
      templateId: row.template_id,
    })
    dialog.id = ''
    dialog.templateId = row.template_id
    dialog.name = row.name
    dialog.version = version
    dialog.description = row.description || ''
    dialog.entryMode = row.entry_mode || 'single'
    dialog.effectiveFrom = today()
    dialog.fieldsText = JSON.stringify(row.fields || [], null, 2)
    dialog.visible = true
  } catch (e: any) {
    ElMessage.error(e?.message || '获取版本失败')
  }
}

async function saveDraft() {
  let fields: unknown
  try {
    fields = JSON.parse(dialog.fieldsText || '[]')
    if (!Array.isArray(fields)) throw new Error('fields 必须是数组')
  } catch {
    ElMessage.warning('字段定义必须是合法的 JSON 数组')
    return
  }
  if (!dialog.templateId.trim() || !dialog.name.trim()) {
    ElMessage.warning('请填写模板标识与名称')
    return
  }
  saving.value = true
  try {
    if (dialog.id) {
      await callApi('updateTemplateRow', {
        id: dialog.id,
        patch: {
          name: dialog.name.trim(),
          description: dialog.description,
          entry_mode: dialog.entryMode,
          effective_from: dialog.effectiveFrom || null,
          fields,
        },
      })
    } else {
      await callApi('createDraft', {
        payload: {
          team_id: ws.currentTeamId,
          template_id: dialog.templateId.trim(),
          version: Number(dialog.version) || 1,
          name: dialog.name.trim(),
          description: dialog.description,
          entry_mode: dialog.entryMode,
          effective_from: dialog.effectiveFrom || null,
          fields,
          scope: { type: 'all' },
        },
      })
    }
    dialog.visible = false
    ElMessage.success('草稿已保存')
    await load()
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function publish(row: TemplateRow) {
  try {
    await ElMessageBox.confirm(`发布「${row.name}」v${row.version}？发布后旧版本会自动归档。`, '发布模板', {
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await callApi('publishTemplate', { id: row.id, today: today() })
    ElMessage.success('已发布')
    await load()
  } catch (e: any) {
    ElMessage.error(e?.message || '发布失败')
  }
}

async function archive(row: TemplateRow) {
  try {
    await ElMessageBox.confirm(`停用「${row.name}」v${row.version}？`, '停用模板', { type: 'warning' })
  } catch {
    return
  }
  try {
    await callApi('updateTemplateRow', { id: row.id, patch: { status: 'archived' } })
    ElMessage.success('已停用')
    await load()
  } catch (e: any) {
    ElMessage.error(e?.message || '停用失败')
  }
}

async function removeDraft(row: TemplateRow) {
  try {
    await ElMessageBox.confirm('删除该草稿？此操作不可恢复。', '删除草稿', { type: 'warning' })
  } catch {
    return
  }
  try {
    await callApi('deleteTemplateRow', { id: row.id })
    ElMessage.success('已删除')
    await load()
  } catch (e: any) {
    ElMessage.error(e?.message || '删除失败')
  }
}
</script>

<template>
  <div class="page">
    <PageHeader title="模板中心" description="草稿编辑、版本发布与停用">
      <el-button type="primary" @click="openCreate">新建模板</el-button>
    </PageHeader>

    <el-card shadow="never">
      <el-table :data="rows" v-loading="loading" size="small" empty-text="暂无模板">
        <el-table-column prop="name" label="名称" min-width="180" />
        <el-table-column prop="template_id" label="模板标识" min-width="150" />
        <el-table-column prop="version" label="版本" width="80" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'published' ? 'success' : row.status === 'draft' ? 'info' : 'warning'">
              {{ row.status === 'published' ? '已发布' : row.status === 'draft' ? '草稿' : '已归档' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="字段数" width="90">
          <template #default="{ row }">{{ (row.fields || []).length }}</template>
        </el-table-column>
        <el-table-column prop="effective_from" label="生效日期" min-width="110" />
        <el-table-column label="操作" min-width="240">
          <template #default="{ row }">
            <template v-if="row.status === 'draft'">
              <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
              <el-button link type="success" @click="publish(row)">发布</el-button>
              <el-button link type="danger" @click="removeDraft(row)">删除</el-button>
            </template>
            <template v-else-if="row.status === 'published'">
              <el-button link type="primary" @click="openNewVersion(row)">新版本</el-button>
              <el-button link type="warning" @click="archive(row)">停用</el-button>
            </template>
            <template v-else>
              <el-button link type="primary" @click="openNewVersion(row)">基于此版本新建</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialog.visible" :title="dialog.id ? '编辑草稿' : '新建模板草稿'" width="640px">
      <el-form label-width="96px">
        <el-form-item label="模板标识">
          <el-input v-model="dialog.templateId" :disabled="!!dialog.id" placeholder="如 daily_report" />
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="dialog.name" maxlength="128" />
        </el-form-item>
        <el-form-item label="版本号">
          <el-input-number v-model="dialog.version" :min="1" :disabled="!!dialog.id" />
        </el-form-item>
        <el-form-item label="录入模式">
          <el-select v-model="dialog.entryMode">
            <el-option label="单条" value="single" />
            <el-option label="多条" value="multiple" />
          </el-select>
        </el-form-item>
        <el-form-item label="生效日期">
          <el-date-picker v-model="dialog.effectiveFrom" type="date" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="dialog.description" type="textarea" :rows="2" maxlength="512" />
        </el-form-item>
        <el-form-item label="字段定义">
          <el-input
            v-model="dialog.fieldsText"
            type="textarea"
            :rows="10"
            placeholder='[{"fieldKey":"amount","label":"金额","type":"decimal","required":true}]'
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveDraft">保存草稿</el-button>
      </template>
    </el-dialog>
  </div>
</template>
