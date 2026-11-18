<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { callApi } from '../api/client'
import PageHeader from '../components/PageHeader.vue'
import { useWorkspaceStore } from '../stores/workspace'
import type { DepartmentNode, WorkspaceMember } from '../api/types'

const ws = useWorkspaceStore()
const activeTab = ref('teams')
const loading = ref(false)
const saving = ref(false)

const deptDialog = reactive({
  visible: false,
  id: '',
  name: '',
  parentId: '',
  leaderUid: '',
})
const teamDialog = reactive({ visible: false, name: '', departmentId: '' })
const deptMoveDialog = reactive({ visible: false, teamId: '', departmentId: '' })
const memberDialog = reactive({ visible: false, id: '', name: '', role: 'member', status: 'active' })

async function reload() {
  if (!ws.currentWorkspaceId) return
  loading.value = true
  try {
    await Promise.all([ws.loadDepartments(), ws.loadMembers()])
  } catch (e: any) {
    ElMessage.error(e?.message || '组织数据加载失败')
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
  await reload()
})

watch(() => ws.currentWorkspaceId, reload)

function openDept(parentId: string | null) {
  deptDialog.id = ''
  deptDialog.name = ''
  deptDialog.parentId = parentId || ''
  deptDialog.leaderUid = ''
  deptDialog.visible = true
}

function editDept(row: DepartmentNode) {
  deptDialog.id = row.id
  deptDialog.name = row.name
  deptDialog.parentId = row.parent_id || ''
  deptDialog.leaderUid = row.leader_uid || ''
  deptDialog.visible = true
}

async function saveDept() {
  if (!deptDialog.name.trim()) {
    ElMessage.warning('请输入部门名称')
    return
  }
  saving.value = true
  try {
    if (deptDialog.id) {
      await callApi('updateDepartment', {
        workspaceId: ws.currentWorkspaceId,
        id: deptDialog.id,
        name: deptDialog.name.trim(),
        leaderUid: deptDialog.leaderUid || '',
      })
    } else {
      await callApi('createDepartment', {
        workspaceId: ws.currentWorkspaceId,
        name: deptDialog.name.trim(),
        parentId: deptDialog.parentId || '',
        leaderUid: deptDialog.leaderUid || '',
      })
    }
    deptDialog.visible = false
    ElMessage.success('已保存')
    await ws.loadDepartments()
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

function openTeam() {
  teamDialog.name = ''
  teamDialog.departmentId = ''
  teamDialog.visible = true
}

async function saveTeam() {
  if (!teamDialog.name.trim()) {
    ElMessage.warning('请输入团队名称')
    return
  }
  saving.value = true
  try {
    await callApi('createTeam', {
      workspaceId: ws.currentWorkspaceId,
      name: teamDialog.name.trim(),
      departmentId: teamDialog.departmentId || '',
    })
    teamDialog.visible = false
    ElMessage.success('团队已创建')
    await ws.loadSpaces()
    await ws.loadMembers()
  } catch (e: any) {
    ElMessage.error(e?.message || '创建失败')
  } finally {
    saving.value = false
  }
}

function openTeamDept(teamId: string, departmentId: string | null) {
  deptMoveDialog.teamId = teamId
  deptMoveDialog.departmentId = departmentId || ''
  deptMoveDialog.visible = true
}

async function saveTeamDept() {
  saving.value = true
  try {
    await callApi('updateTeamConfig', {
      teamId: deptMoveDialog.teamId,
      departmentId: deptMoveDialog.departmentId || '',
    })
    deptMoveDialog.visible = false
    ElMessage.success('团队部门已更新')
    await ws.loadSpaces()
  } catch (e: any) {
    ElMessage.error(e?.message || '更新失败')
  } finally {
    saving.value = false
  }
}

function editMember(row: WorkspaceMember) {
  memberDialog.id = row.id
  memberDialog.name = row.name
  memberDialog.role = row.role
  memberDialog.status = row.status
  memberDialog.visible = true
}

async function saveMember() {
  saving.value = true
  try {
    await callApi('updateWorkspaceMember', {
      workspaceId: ws.currentWorkspaceId,
      id: memberDialog.id,
      patch: {
        name: memberDialog.name.trim(),
        role: memberDialog.role,
        status: memberDialog.status,
      },
    })
    memberDialog.visible = false
    ElMessage.success('成员已更新')
    await ws.loadMembers()
  } catch (e: any) {
    ElMessage.error(e?.message || '更新失败')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="page">
    <PageHeader title="组织管理" description="空间、部门、团队与成员" />

    <el-row :gutter="16" v-loading="loading">
      <el-col :span="7">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>部门结构</span>
              <el-button size="small" type="primary" plain @click="openDept(null)">新建部门</el-button>
            </div>
          </template>
          <el-tree
            :data="ws.departments"
            node-key="id"
            default-expand-all
            :props="{ label: 'name', children: 'children' }"
            empty-text="暂无部门"
          >
            <template #default="{ data }">
              <div class="tree-node">
                <span>{{ data.name }}</span>
                <span class="node-actions">
                  <el-button link size="small" @click.stop="openDept(data.id)">子部门</el-button>
                  <el-button link size="small" @click.stop="editDept(data)">编辑</el-button>
                </span>
              </div>
            </template>
          </el-tree>
        </el-card>
      </el-col>

      <el-col :span="17">
        <el-card shadow="never">
          <el-tabs v-model="activeTab">
            <el-tab-pane label="团队" name="teams">
              <div class="toolbar">
                <el-button type="primary" plain @click="openTeam">新建团队</el-button>
              </div>
              <el-table :data="ws.teams" size="small" empty-text="暂无团队">
                <el-table-column prop="name" label="团队" min-width="150" />
                <el-table-column prop="team_id" label="团队编号" min-width="110" />
                <el-table-column label="部门" min-width="130">
                  <template #default="{ row }">
                    {{ ws.departmentName(row.department_id) || '—' }}
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="110">
                  <template #default="{ row }">
                    <el-button link type="primary" @click="openTeamDept(row.team_id, row.department_id)">
                      调整部门
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>

            <el-tab-pane label="成员" name="members">
              <el-table :data="ws.members" size="small" empty-text="暂无成员">
                <el-table-column prop="name" label="姓名" min-width="110" />
                <el-table-column prop="user_id" label="用户 ID" min-width="180" show-overflow-tooltip />
                <el-table-column prop="role" label="角色" width="100" />
                <el-table-column prop="status" label="状态" width="90" />
                <el-table-column prop="joined_at" label="加入时间" min-width="150" />
                <el-table-column label="操作" width="90">
                  <template #default="{ row }">
                    <el-button link type="primary" @click="editMember(row)">编辑</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
          </el-tabs>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="deptDialog.visible" :title="deptDialog.id ? '编辑部门' : '新建部门'" width="420px">
      <el-form label-width="90px">
        <el-form-item label="部门名称">
          <el-input v-model="deptDialog.name" maxlength="128" />
        </el-form-item>
        <el-form-item label="上级部门">
          <el-select v-model="deptDialog.parentId" clearable placeholder="无（根部门）" :disabled="!!deptDialog.id">
            <el-option
              v-for="dept in ws.departments"
              :key="dept.id"
              :label="dept.name"
              :value="dept.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="负责人 UID">
          <el-input v-model="deptDialog.leaderUid" placeholder="可选，需为本空间成员" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="deptDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveDept">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="teamDialog.visible" title="新建团队" width="420px">
      <el-form label-width="90px">
        <el-form-item label="团队名称">
          <el-input v-model="teamDialog.name" maxlength="128" />
        </el-form-item>
        <el-form-item label="所属部门">
          <el-select v-model="teamDialog.departmentId" clearable placeholder="不指定">
            <el-option
              v-for="dept in ws.departments"
              :key="dept.id"
              :label="dept.name"
              :value="dept.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="teamDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveTeam">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="deptMoveDialog.visible" title="调整团队部门" width="420px">
      <el-form label-width="90px">
        <el-form-item label="所属部门">
          <el-select v-model="deptMoveDialog.departmentId" clearable placeholder="不指定">
            <el-option
              v-for="dept in ws.departments"
              :key="dept.id"
              :label="dept.name"
              :value="dept.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="deptMoveDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveTeamDept">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="memberDialog.visible" title="编辑成员" width="420px">
      <el-form label-width="90px">
        <el-form-item label="姓名">
          <el-input v-model="memberDialog.name" maxlength="64" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="memberDialog.role">
            <el-option label="所有者" value="owner" />
            <el-option label="管理员" value="admin" />
            <el-option label="成员" value="member" />
            <el-option label="只读" value="viewer" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="memberDialog.status">
            <el-option label="启用" value="active" />
            <el-option label="停用" value="disabled" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="memberDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveMember">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.tree-node {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  gap: 8px;
}

.node-actions {
  opacity: 0;
  transition: opacity 0.15s;
}

.tree-node:hover .node-actions {
  opacity: 1;
}
</style>
