const session = require('../../utils/session')
const store = require('../../utils/store')

const ROLE_TEXT = {
  owner: '所有者',
  admin: '管理员',
  manager: '管理员',
  viewer: '只读',
  member: '成员',
}

function roleText(role) {
  return ROLE_TEXT[role] || '成员'
}

Page({
  data: {
    checking: true,
    signedIn: false,
    hasOrg: false,
    spaces: [],
    workspace: null,
    workspaceRole: '',
    workspaceRoleText: '',
    teams: [],
    currentWorkspaceId: '',
    currentTeamId: '',
    mode: 'join', // join | create | workspace
    teamName: '',
    workspaceName: '',
    myName: '',
    inviteCode: '',
    busy: false,
    errorText: '',
  },

  onShow: async function () {
    this.setData({ checking: true, errorText: '' })
    try {
      const ctx = await session.loadContext(true)
      if (!ctx.uid) {
        wx.switchTab({ url: '/pages/index/index' })
        return
      }
      const spaces = await store.listMyWorkspaces()
      this.setData({
        checking: false,
        signedIn: true,
        hasOrg: !!(ctx.workspace || (spaces && spaces.length)),
        spaces: spaces || [],
        workspace: ctx.workspace || null,
        workspaceRole: ctx.workspaceRole || '',
        workspaceRoleText: roleText(ctx.workspaceRole),
        teams: ctx.teams || [],
        currentWorkspaceId: ctx.workspace ? ctx.workspace.id : '',
        currentTeamId: ctx.team ? ctx.team.team_id : '',
        mode: 'join',
      })
    } catch (e) {
      this.setData({ checking: false, errorText: e.message || '加载失败' })
    }
  },

  switchMode: function (e) {
    this.setData({ mode: e.currentTarget.dataset.mode, errorText: '' })
  },

  onTeamName: function (e) {
    this.setData({ teamName: e.detail.value })
  },

  onWorkspaceName: function (e) {
    this.setData({ workspaceName: e.detail.value })
  },

  onMyName: function (e) {
    this.setData({ myName: e.detail.value })
  },

  onInviteCode: function (e) {
    this.setData({ inviteCode: e.detail.value.trim().toUpperCase() })
  },

  // 切换团队：同一空间内直接切；跨空间由服务端校验归属
  doSwitchTeam: async function (e) {
    const teamId = e.currentTarget.dataset.teamId
    if (!teamId || teamId === this.data.currentTeamId || this.data.busy) return
    this.setData({ busy: true, errorText: '' })
    try {
      const ctx = await session.switchTeam(teamId)
      this.setData({
        workspace: ctx.workspace,
        workspaceRole: ctx.workspaceRole || '',
        workspaceRoleText: roleText(ctx.workspaceRole),
        teams: ctx.teams || [],
        currentWorkspaceId: ctx.workspace ? ctx.workspace.id : '',
        currentTeamId: ctx.team ? ctx.team.team_id : '',
      })
      wx.showToast({ title: '已切换团队', icon: 'success' })
      setTimeout(function () {
        wx.switchTab({ url: '/pages/index/index' })
      }, 600)
    } catch (err) {
      this.setData({ errorText: err.message || '切换失败' })
    }
    this.setData({ busy: false })
  },

  // 切换空间：进入该空间的默认团队（无团队时仅停留在空间）
  doSwitchSpace: async function (e) {
    const workspaceId = e.currentTarget.dataset.workspaceId
    if (!workspaceId || workspaceId === this.data.currentWorkspaceId || this.data.busy) return
    this.setData({ busy: true, errorText: '' })
    try {
      const ctx = await session.switchSpace(workspaceId)
      this.setData({
        workspace: ctx.workspace,
        workspaceRole: ctx.workspaceRole || '',
        workspaceRoleText: roleText(ctx.workspaceRole),
        teams: ctx.teams || [],
        currentWorkspaceId: ctx.workspace ? ctx.workspace.id : '',
        currentTeamId: ctx.team ? ctx.team.team_id : '',
      })
      wx.showToast({ title: '已切换空间', icon: 'none' })
    } catch (err) {
      this.setData({ errorText: err.message || '切换失败' })
    }
    this.setData({ busy: false })
  },

  doCreate: async function () {
    const name = this.data.teamName.trim()
    const myName = this.data.myName.trim() || '负责人'
    if (!name) {
      this.setData({ errorText: '请填写团队名称' })
      return
    }
    this.setData({ busy: true, errorText: '' })
    try {
      const res = await store.createTeam(name, myName)
      await session.switchTeam(res.team.team_id)
      store.logAction(res.team.team_id, 'team_create', 'teams', res.team.team_id, { name: name })
      wx.showToast({ title: '团队已创建', icon: 'success' })
      setTimeout(function () {
        wx.switchTab({ url: '/pages/index/index' })
      }, 800)
    } catch (e) {
      this.setData({ errorText: e.message || '创建失败' })
    }
    this.setData({ busy: false })
  },

  doCreateWorkspace: async function () {
    const workspaceName = this.data.workspaceName.trim()
    const teamName = this.data.teamName.trim()
    const myName = this.data.myName.trim() || '负责人'
    if (!workspaceName) {
      this.setData({ errorText: '请填写工作空间名称' })
      return
    }
    this.setData({ busy: true, errorText: '' })
    try {
      const res = await store.createWorkspace(workspaceName, myName, teamName)
      if (res.team) await session.switchTeam(res.team.team_id)
      else await session.switchSpace(res.workspace.id)
      wx.showToast({ title: '工作空间已创建', icon: 'success' })
      setTimeout(function () {
        wx.switchTab({ url: '/pages/index/index' })
      }, 800)
    } catch (e) {
      this.setData({ errorText: e.message || '创建失败' })
    }
    this.setData({ busy: false })
  },

  doJoin: async function () {
    const code = this.data.inviteCode.trim()
    const myName = this.data.myName.trim() || '成员'
    if (!code) {
      this.setData({ errorText: '请输入邀请码' })
      return
    }
    this.setData({ busy: true, errorText: '' })
    try {
      const team = await store.findTeamByCode(code)
      if (!team) {
        this.setData({ errorText: '邀请码不存在，请确认后重试' })
        this.setData({ busy: false })
        return
      }
      await store.joinTeam(code, myName)
      await session.switchTeam(code)
      store.logAction(code, 'member_join', 'members', session.currentUid(), { name: myName })
      wx.showToast({ title: '已加入 ' + team.name, icon: 'success' })
      setTimeout(function () {
        wx.switchTab({ url: '/pages/index/index' })
      }, 800)
    } catch (e) {
      this.setData({ errorText: e.message || '加入失败' })
    }
    this.setData({ busy: false })
  },
})
