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
      // 应提交口径由服务端统一计算（任务优先，无任务回退模板范围）
      const status = await store.getReportTaskStatus({
        teamId: ctx.team.team_id,
        date: today,
      })
      const expected = status.expected || []
      const draftCount = expected.filter(function (m) {
        return m.draft
      }).length
      this.setData({
        loading: false,
        denied: false,
        todayText: today,
        shouldCount: status.expectedCount || 0,
        submittedCount: status.submittedCount || 0,
        draftCount: draftCount,
        rateText: status.rateText || '0%',
        ratePercent: status.rate || 0,
        missing: status.missing || [],
        hasTemplate: !!status.hasTemplate,
        templateName: status.task ? status.task.title : (status.templateName || ''),
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
