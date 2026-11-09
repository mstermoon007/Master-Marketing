const session = require('../../../utils/session')
const store = require('../../../utils/store')
const dateUtil = require('../../../utils/date')

Page({
  data: {
    loading: true,
    denied: false,
    errorText: '',
    todayText: '',
    shouldCount: 0,
    submittedCount: 0,
    draftCount: 0,
    rateText: '0%',
    ratePercent: 0,
    missing: [],
    hasTemplate: false,
    templateName: '',
  },

  onShow: async function () {
    this.setData({ loading: true, errorText: '' })
    try {
      const ctx = await session.loadContext()
      if (!ctx.member || !ctx.team) {
        wx.switchTab({ url: '/pages/index/index' })
        return
      }
      if (!session.isManager(ctx.member)) {
        this.setData({ loading: false, denied: true })
        return
      }
      await this.loadDashboard(ctx)
    } catch (e) {
      this.setData({ loading: false, errorText: e.message || '加载失败' })
    }
  },

  loadDashboard: async function (ctx) {
    try {
      const today = dateUtil.today()
      // 忽略查询者自身范围（P1-2）：范围由模板 scope 对每个成员判定
      const tpl = await store.getActiveTemplate(ctx.team.team_id, ctx.member, true)
      const members = await store.listMembers(ctx.team.team_id)
      const active = members.filter(function (m) {
        return m.status === 'active' && (!tpl || store.inScope(tpl.scope, m))
      })
      const targets = active
      const entries = await store.listTeamEntries(ctx.team.team_id, today, today)
      const byUser = {}
      entries.forEach(function (en) {
        byUser[en.user_id] = en
      })
      const missing = []
      let submitted = 0
      let drafts = 0
      targets.forEach(function (m) {
        const en = byUser[m.user_id]
        if (en && en.status === 'submitted') {
          submitted += 1
        } else {
          if (en && en.status === 'draft') drafts += 1
          missing.push({
            userId: m.user_id,
            name: m.name,
            role: m.role,
            draft: !!(en && en.status === 'draft'),
          })
        }
      })
      const should = targets.length
      const rate = should > 0 ? Math.round((submitted / should) * 100) : 0
      this.setData({
        loading: false,
        denied: false,
        todayText: today,
        shouldCount: should,
        submittedCount: submitted,
        draftCount: drafts,
        rateText: rate + '%',
        ratePercent: rate,
        missing: missing,
        hasTemplate: !!tpl,
        templateName: tpl ? tpl.name : '',
      })
    } catch (e) {
      this.setData({ loading: false, errorText: e.message || '加载失败' })
    }
  },

  copyUrgeText: function () {
    const names = this.data.missing
      .map(function (m) {
        return m.name + (m.draft ? '（草稿）' : '')
      })
      .join('、')
    if (!names) {
      wx.showToast({ title: '今日已全部提交', icon: 'success' })
      return
    }
    const text =
      '【成果催填】' +
      this.data.todayText +
      ' ' +
      this.data.templateName +
      '\n已提交 ' +
      this.data.submittedCount +
      '/' +
      this.data.shouldCount +
      ' 人\n还未提交：' +
      names +
      '\n请今天 24:00 前完成提交，谢谢！'
    wx.setClipboardData({
      data: text,
      success: function () {
        wx.showToast({ title: '催填文案已复制', icon: 'success' })
      },
    })
  },

  refresh: function () {
    this.onShow()
  },
})
