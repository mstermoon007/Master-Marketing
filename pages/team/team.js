const session = require('../../utils/session')
const store = require('../../utils/store')

Page({
  data: {
    checking: true,
    signedIn: false,
    mode: 'join', // join | create
    teamName: '',
    myName: '',
    inviteCode: '',
    busy: false,
    errorText: '',
    myTeams: [],
  },

  onShow: async function () {
    this.setData({ checking: true })
    try {
      const ctx = await session.loadContext()
      if (!ctx.uid) {
        // 未登录：回首页登录
        wx.switchTab({ url: '/pages/index/index' })
        return
      }
      this.setData({ checking: false, signedIn: true, myName: (ctx.session.user && ctx.session.user.name) || '' })
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

  onMyName: function (e) {
    this.setData({ myName: e.detail.value })
  },

  onInviteCode: function (e) {
    this.setData({ inviteCode: e.detail.value.trim().toUpperCase() })
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
      const ctx = await session.loadContext()
      const res = await store.createTeam(name, ctx.uid, myName)
      session.clearContext()
      await session.loadContext(true)
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

  doJoin: async function () {
    const code = this.data.inviteCode.trim()
    const myName = this.data.myName.trim() || '成员'
    if (!code) {
      this.setData({ errorText: '请输入邀请码' })
      return
    }
    this.setData({ busy: true, errorText: '' })
    try {
      const ctx = await session.loadContext()
      const team = await store.findTeamByCode(code)
      if (!team) {
        this.setData({ errorText: '邀请码不存在，请确认后重试' })
        this.setData({ busy: false })
        return
      }
      await store.joinTeam(code, ctx.uid, myName)
      session.clearContext()
      await session.loadContext(true)
      store.logAction(code, 'member_join', 'members', ctx.uid, { name: myName })
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
