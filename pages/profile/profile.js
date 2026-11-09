const session = require('../../utils/session')
const store = require('../../utils/store')

Page({
  data: {
    authState: 'checking',
    signedIn: false,
    member: null,
    team: null,
    isManager: false,
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
        isManager: session.isManager(ctx.member),
        inviteCode: ctx.team ? ctx.team.team_id : '',
        memberSeeTeamTotal: ctx.team && ctx.team.config ? !!ctx.team.config.memberSeeTeamTotal : false,
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
