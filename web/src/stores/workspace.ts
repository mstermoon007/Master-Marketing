import { defineStore } from 'pinia'
import { callApi } from '../api/client'
import type { DepartmentNode, SpaceSummary, TeamSummary, WorkspaceMember } from '../api/types'

const WS_KEY = 'jinribao_web_workspace'
const TEAM_KEY = 'jinribao_web_team'

export const useWorkspaceStore = defineStore('workspace', {
  state: () => ({
    spaces: [] as SpaceSummary[],
    currentWorkspaceId: localStorage.getItem(WS_KEY) || '',
    currentTeamId: localStorage.getItem(TEAM_KEY) || '',
    departments: [] as DepartmentNode[],
    members: [] as WorkspaceMember[],
    loading: false,
  }),
  getters: {
    currentSpace(state): SpaceSummary | undefined {
      return state.spaces.find((s) => s.workspace.id === state.currentWorkspaceId)
    },
    teams(): TeamSummary[] {
      return this.currentSpace?.teams || []
    },
    currentTeam(): TeamSummary | undefined {
      return this.teams.find((t) => t.team_id === this.currentTeamId)
    },
    departmentName() {
      const flat: Record<string, string> = {}
      const walk = (nodes: DepartmentNode[]) => {
        nodes.forEach((node) => {
          flat[node.id] = node.name
          walk(node.children || [])
        })
      }
      walk(this.departments)
      return (id: string | null | undefined) => (id ? flat[id] || '' : '')
    },
  },
  actions: {
    async loadSpaces() {
      this.loading = true
      try {
        this.spaces = await callApi<SpaceSummary[]>('listMyWorkspaces')
        const exists = this.spaces.some((s) => s.workspace.id === this.currentWorkspaceId)
        if (!exists) {
          this.currentWorkspaceId = this.spaces[0]?.workspace.id || ''
        }
        const teamExists = this.teams.some((t) => t.team_id === this.currentTeamId)
        if (!teamExists) {
          this.currentTeamId = this.teams[0]?.team_id || ''
        }
        this.persist()
      } finally {
        this.loading = false
      }
    },
    selectWorkspace(id: string) {
      if (id === this.currentWorkspaceId) return
      this.currentWorkspaceId = id
      this.currentTeamId = this.currentSpace?.teams[0]?.team_id || ''
      this.departments = []
      this.members = []
      this.persist()
    },
    selectTeam(id: string) {
      this.currentTeamId = id
      localStorage.setItem(TEAM_KEY, id)
    },
    persist() {
      localStorage.setItem(WS_KEY, this.currentWorkspaceId)
      localStorage.setItem(TEAM_KEY, this.currentTeamId)
    },
    async loadDepartments() {
      if (!this.currentWorkspaceId) return
      this.departments = await callApi<DepartmentNode[]>('listDepartments', {
        workspaceId: this.currentWorkspaceId,
      })
    },
    async loadMembers() {
      if (!this.currentWorkspaceId) return
      this.members = await callApi<WorkspaceMember[]>('listWorkspaceMembers', {
        workspaceId: this.currentWorkspaceId,
      })
    },
  },
})
