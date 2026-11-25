<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useWorkspaceStore } from '../stores/workspace'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const ws = useWorkspaceStore()
const auth = useAuthStore()

const menus = [
  { path: '/dashboard', label: '工作台' },
  { path: '/org', label: '组织管理' },
  { path: '/templates', label: '模板中心' },
  { path: '/tasks', label: '填报任务' },
  { path: '/data', label: '数据中心' },
  { path: '/analysis', label: '分析结果' },
  { path: '/audit', label: '操作审计' },
]

const pageTitle = computed(() => menus.find((m) => route.path.startsWith(m.path))?.label || '')

onMounted(async () => {
  if (ws.spaces.length) return
  try {
    await ws.loadSpaces()
  } catch (e: any) {
    ElMessage.error(e?.message || '加载工作空间失败')
    auth.logout()
    router.replace('/login')
  }
})

function onWorkspaceChange(id: string) {
  ws.selectWorkspace(id)
}

function onTeamChange(id: string) {
  ws.selectTeam(id)
}

function logout() {
  auth.logout()
  router.replace('/login')
}
</script>

<template>
  <el-container class="shell">
    <el-aside width="220px" class="aside">
      <div class="brand">
        <div class="brand-name">报数机器人AI</div>
        <div class="brand-sub">管理后台</div>
      </div>
      <el-menu :default-active="route.path" router class="menu">
        <el-menu-item v-for="menu in menus" :key="menu.path" :index="menu.path">
          {{ menu.label }}
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="left">
          <el-select
            :model-value="ws.currentWorkspaceId"
            placeholder="选择工作空间"
            class="select"
            @change="onWorkspaceChange"
          >
            <el-option
              v-for="space in ws.spaces"
              :key="space.workspace.id"
              :label="space.workspace.name"
              :value="space.workspace.id"
            />
          </el-select>
          <el-select
            :model-value="ws.currentTeamId"
            placeholder="选择团队"
            class="select"
            :disabled="!ws.teams.length"
            @change="onTeamChange"
          >
            <el-option
              v-for="team in ws.teams"
              :key="team.team_id"
              :label="team.name"
              :value="team.team_id"
            />
          </el-select>
          <span class="muted">{{ pageTitle }}</span>
        </div>
        <div class="right">
          <span class="muted role">管理权限</span>
          <el-button link type="primary" @click="logout">退出登录</el-button>
        </div>
      </el-header>

      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.shell {
  height: 100vh;
}

.aside {
  background: #1f2d3d;
  color: #fff;
  display: flex;
  flex-direction: column;
}

.brand {
  padding: 22px 20px 16px;
}

.brand-name {
  font-size: 17px;
  font-weight: 600;
}

.brand-sub {
  margin-top: 4px;
  font-size: 12px;
  color: #8a94a6;
}

.menu {
  border-right: none;
  background: transparent;
}

.menu :deep(.el-menu-item) {
  color: #c4ccd8;
}

.menu :deep(.el-menu-item.is-active) {
  color: #fff;
  background: #2f415a;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #e6eaf0;
}

.left,
.right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.select {
  width: 180px;
}

.role {
  font-size: 13px;
}

.main {
  background: #f5f7fa;
  padding: 0;
  overflow-y: auto;
}
</style>
