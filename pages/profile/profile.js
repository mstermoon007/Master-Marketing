const session = require('../../utils/session')
const store = require('../../utils/store')

const ROLE_TEXT = {
  owner: '负责人',
  admin: '空间管理员',
  manager: '管理员',
  viewer: '只读',
  member: '成员',
}

function roleText(member) {
  if (!member) return ''
  return ROLE_TEXT[member.effective_role || member.role] || '成员'
}

Page({
  data: {
    authState: 'checking',
    signedIn: false,
    member: null,
    team: null,
    workspace: null,
    workspaceRole: '',
    roleText: '',
    isManager: false,
    isOwner: false,
    memberSeeTeamTotal: false,
    inviteCode: '',
    errorText: '',
  },

  onShow: async function () {
    this.setData({ authState: 'checking' })
    try {
      const ctx = await session.loadContext()
      if (!ctx.uid) {
        this.setData({ authState: 'signed-out', signedIn: false })
        return
      }
      this.setData({
        authState: 'ready',
        signedIn: true,
        member: ctx.member,
        team: ctx.team,
        workspace: ctx.workspace || null,
        workspaceRole: ctx.workspaceRole || '',
        roleText: roleText(ctx.member),
        isManager: session.isManager(ctx.member),
        isOwner: !!ctx.member && (ctx.member.effective_role || ctx.member.role) === 'owner',
        inviteCode: ctx.team ? ctx.team.team_id : '',
        memberSeeTeamTotal: ctx.team && ctx.team.config ? !!ctx.team.config.memberSeeTeamTotal : false,
        errorText: '',
      })
    } catch (e) {
      // 保留登录态，停用成员仍能看到「退出登录」；同时展示明确原因
      this.setData({
        authState: 'ready',
        signedIn: session.hasSession(),
        errorText: (e && e.message) || '加载失败',
      })
    }
  },

  copyInvite: function () {
    if (!this.data.inviteCode) return
    wx.setClipboardData({
      data: this.data.inviteCode,
      success: function () {
        wx.showToast({ title: '邀请码已复制', icon: 'success' })
      },
    })
  },

  toggleTeamTotal: async function (e) {
    const checked = e.detail.value
    try {
      const ctx = await session.loadContext()
      if (!ctx.team) {
        wx.showToast({ title: '请先选择团队', icon: 'none' })
        this.setData({ memberSeeTeamTotal: !checked })
        return
      }
      const config = Object.assign({}, (ctx.team && ctx.team.config) || {}, { memberSeeTeamTotal: checked })
      await store.updateTeamConfig(ctx.team.team_id, config)
      ctx.team.config = config
      this.setData({ memberSeeTeamTotal: checked })
    } catch (err) {
      wx.showToast({ title: err.message || '设置失败', icon: 'none' })
      this.setData({ memberSeeTeamTotal: !checked })
    }
  },

  goDashboard: function () {
    wx.navigateTo({ url: '/pages/admin/dashboard/dashboard' })
  },

  goTemplates: function () {
    wx.navigateTo({ url: '/pages/admin/templates/templates' })
  },

  goReports: function () {
    wx.navigateTo({ url: '/pages/admin/reports/reports' })
  },

  goMembers: function () {
    wx.navigateTo({ url: '/pages/admin/members/members' })
  },

  goTeamPage: function () {
    wx.navigateTo({ url: '/pages/team/team' })
  },

  backHome: function () {
    wx.switchTab({ url: '/pages/index/index' })
  },

  doSignOut: async function () {
    await session.signOut()
    wx.showToast({ title: '已退出', icon: 'success' })
    setTimeout(function () {
      wx.switchTab({ url: '/pages/index/index' })
    }, 600)
  },
})
