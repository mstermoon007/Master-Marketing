const session = require('../../../utils/session')
const store = require('../../../utils/store')
const dateUtil = require('../../../utils/date')

function growthText(item) {
  if (!item) return '数据不足'
  if (item.state === 'incomplete') return '周期未结束'
  if (item.growth === null || item.growth === undefined) return '无基线'
  return (item.growth * 100).toFixed(1) + '%'
}

function decorateMetrics(list) {
  return (list || []).map(function (metric) {
    if (metric.code === 'PERIOD_GROWTH') {
      return Object.assign({}, metric, {
        growth: (metric.growth || []).map(function (item) {
          return Object.assign({}, item, { displayText: growthText(item) })
        }),
      })
    }
    return metric
  })
}

function decorateTask(task) {
  return Object.assign({}, task, {
    dateText: task.from + ' 至 ' + task.to,
    timeText: task.createdAt ? task.createdAt.replace('T', ' ').slice(0, 16) : '',
  })
}

Page({
  data: {
    loading: true,
    denied: false,
    errorText: '',
    running: false,
    showRules: false,
    from: '',
    to: '',
    todayText: '',
    teamName: '',
    metricDefs: [],
    rules: [],
    tasks: [],
    result: null,
    overall: {},
    metrics: [],
    dailyChips: [],
    findings: [],
    quality: [],
  },

  ctx: null,

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
      this.ctx = ctx
      const today = dateUtil.today()
      this.setData({
        loading: false,
        teamName: ctx.team.name,
        todayText: today,
        from: this.data.from || dateUtil.addDays(today, -6),
        to: this.data.to || today,
      })
      await this.loadOverview()
    } catch (err) {
      this.setData({ loading: false, errorText: err.message || '加载失败' })
    }
  },

  loadOverview: async function () {
    const overview = await store.getAnalysisOverview(this.ctx.team.team_id)
    this.setData({
      metricDefs: overview.metrics || [],
      rules: overview.rules || [],
      tasks: (overview.tasks || []).map(decorateTask),
    })
    if (overview.latest) this.applyView(overview.latest)
  },

  applyView: function (view) {
    const summary = (view.result && view.result.summary) || {}
    const quality = (summary.quality && summary.quality.checks) || []
    this.setData({
      result: {
        task: decorateTask(view.task || {}),
        snapshot: (view.result && view.result.dataSnapshotTime) || '',
        executionId: (view.result && view.result.executionId) || '',
        reportText: (view.result && view.result.reportText) || '',
        reused: !!view.reused,
      },
      overall: summary.overall || {},
      metrics: decorateMetrics(summary.metrics),
      dailyChips: (summary.daily || []).map(function (day) {
        return {
          date: (day.date || '').slice(5),
          text: day.submittedCount + '/' + day.expectedCount,
          rate: day.rateText,
        }
      }),
      findings: view.findings || [],
      quality: quality.filter(function (item) { return item.count > 0 }),
    })
  },

  onFrom: function (e) {
    this.setData({ from: e.detail.value })
  },

  onTo: function (e) {
    this.setData({ to: e.detail.value })
  },

  toggleRules: function () {
    this.setData({ showRules: !this.data.showRules })
  },

  runAnalysis: async function () {
    if (this.data.running) return
    if (!this.data.from || !this.data.to) {
      wx.showToast({ title: '请选择分析周期', icon: 'none' })
      return
    }
    if (this.data.from > this.data.to) {
      wx.showToast({ title: '结束日期不能早于开始日期', icon: 'none' })
      return
    }
    this.setData({ running: true, errorText: '' })
    try {
      const view = await store.runAnalysis({
        teamId: this.ctx.team.team_id,
        from: this.data.from,
        to: this.data.to,
      })
      this.applyView(view)
      wx.showToast({
        title: view.reused ? '已存在相同分析结果' : '分析完成',
        icon: 'none',
      })
      const tasks = await store.listAnalysisTasks(this.ctx.team.team_id, 20)
      this.setData({ tasks: tasks.map(decorateTask) })
    } catch (err) {
      this.setData({ errorText: err.message || '分析失败，请稍后重试' })
    } finally {
      this.setData({ running: false })
    }
  },

  onTaskTap: async function (e) {
    const id = e.currentTarget.dataset.id
    if (!id) return
    try {
      const view = await store.getAnalysisTask(id)
      this.applyView(view)
      this.setData({ showRules: false })
    } catch (err) {
      wx.showToast({ title: err.message || '读取失败', icon: 'none' })
    }
  },

  onRetry: async function (e) {
    const id = e.currentTarget.dataset.id
    if (!id || this.data.running) return
    this.setData({ running: true, errorText: '' })
    try {
      const view = await store.retryAnalysisTask(id)
      this.applyView(view)
      const tasks = await store.listAnalysisTasks(this.ctx.team.team_id, 20)
      this.setData({ tasks: tasks.map(decorateTask) })
      wx.showToast({ title: '重试完成', icon: 'none' })
    } catch (err) {
      this.setData({ errorText: err.message || '重试失败' })
    } finally {
      this.setData({ running: false })
    }
  },
})
