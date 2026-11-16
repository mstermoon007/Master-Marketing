const session = require('../../../utils/session')
const store = require('../../../utils/store')
const dateUtil = require('../../../utils/date')

const ROLE_NAMES = { owner: '负责人', manager: '管理员', member: '成员' }

function scopeText(scope) {
  if (!scope || !scope.type || scope.type === 'all') return '全员'
  if (scope.type === 'members') {
    return '指定成员（' + (scope.memberIds || []).length + ' 人）'
  }
  if (scope.type === 'roles') {
    const names = (scope.roles || []).map(function (r) {
      return ROLE_NAMES[r] || r
    })
    return '指定角色：' + names.join('、')
  }
  return '全员'
}

Page({
  data: {
    loading: true,
    denied: false,
    errorText: '',
    todayText: '',
    tasks: [],
    expandedId: '',
    templates: [],
    templateNames: [],
    templateIndex: 0,
    templateScopeText: '全员',
    showCreate: false,
    creating: false,
    title: '',
    startDate: '',
    endDate: '',
    dueTime: '',
    workdaysOnly: false,
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
        todayText: today,
        startDate: this.data.startDate || today,
      })
      await this.loadAll(ctx)
    } catch (e) {
      this.setData({ loading: false, errorText: e.message || '加载失败' })
    }
  },

  loadAll: async function (ctx) {
    const results = await Promise.all([
      store.listReportTasks(ctx.team.team_id),
      store.listPublishedTemplates(ctx.team.team_id),
    ])
    const tasks = results[0] || []
    // 同一 template_id 只保留最高版本，避免创建任务时选到历史版本
    const byTemplate = {}
    ;(results[1] || []).forEach(function (t) {
      const current = byTemplate[t.template_id]
      if (!current || Number(t.version) > Number(current.version)) {
        byTemplate[t.template_id] = t
      }
    })
    const templates = Object.keys(byTemplate).map(function (key) {
      return byTemplate[key]
    })
    const names = templates.map(function (t) {
      return t.name + ' · v' + t.version
    })
    let index = this.data.templateIndex
    if (index >= templates.length) index = 0
    this.setData({
      loading: false,
      denied: false,
      tasks: tasks,
      templates: templates,
      templateNames: names,
      templateIndex: index,
      templateScopeText: scopeText(templates[index] && templates[index].scope),
    })
  },

  toggleCreate: function () {
    this.setData({ showCreate: !this.data.showCreate })
  },

  onTitle: function (e) {
    this.setData({ title: e.detail.value })
  },

  onTemplateChange: function (e) {
    const index = Number(e.detail.value)
    const tpl = this.data.templates[index]
    this.setData({
      templateIndex: index,
      templateScopeText: scopeText(tpl && tpl.scope),
    })
  },

  onStartDate: function (e) {
    this.setData({ startDate: e.detail.value })
  },

  onEndDate: function (e) {
    this.setData({ endDate: e.detail.value })
  },

  clearEndDate: function () {
    this.setData({ endDate: '' })
  },

  onDueTime: function (e) {
    this.setData({ dueTime: e.detail.value })
  },

  clearDueTime: function () {
    this.setData({ dueTime: '' })
  },

  onWorkdays: function (e) {
    this.setData({ workdaysOnly: e.detail.value })
  },

  onCreate: async function () {
    if (this.data.creating) return
    const title = (this.data.title || '').trim()
    if (!title) {
      wx.showToast({ title: '请填写任务名称', icon: 'none' })
      return
    }
    const tpl = this.data.templates[this.data.templateIndex]
    if (!tpl) {
      wx.showToast({ title: '请先发布一个模板', icon: 'none' })
      return
    }
    if (!this.data.startDate) {
      wx.showToast({ title: '请选择开始日期', icon: 'none' })
      return
    }
    if (this.data.endDate && this.data.endDate < this.data.startDate) {
      wx.showToast({ title: '结束日期不能早于开始日期', icon: 'none' })
      return
    }
    this.setData({ creating: true })
    try {
      await store.createReportTask({
        team_id: this.ctx.team.team_id,
        title: title,
        template_id: tpl.template_id,
        template_version: tpl.version,
        start_date: this.data.startDate,
        end_date: this.data.endDate || null,
        due_time: this.data.dueTime || null,
        workdays_only: !!this.data.workdaysOnly,
        // 下发范围快照模板当前配置，之后模板调整不影响已创建任务
        scope: tpl.scope || { type: 'all' },
      })
      this.setData({
        creating: false,
        showCreate: false,
        title: '',
        endDate: '',
        dueTime: '',
        workdaysOnly: false,
      })
      wx.showToast({ title: '任务已创建', icon: 'success' })
      await this.loadAll(this.ctx)
    } catch (e) {
      this.setData({ creating: false })
      wx.showToast({ title: e.message || '创建失败', icon: 'none' })
    }
  },

  toggleProgress: async function (e) {
    const id = e.currentTarget.dataset.id
    if (this.data.expandedId === id) {
      this.setData({ expandedId: '' })
      return
    }
    wx.showLoading({ title: '加载中' })
    try {
      const progress = await store.getReportTaskStatus({
        teamId: this.ctx.team.team_id,
        taskId: id,
        date: this.data.todayText,
      })
      const tasks = this.data.tasks.map(function (t) {
        return t.id === id ? Object.assign({}, t, { progress: progress }) : t
      })
      this.setData({ expandedId: id, tasks: tasks })
    } catch (err) {
      wx.showToast({ title: err.message || '加载失败', icon: 'none' })
    } finally {
      wx.hideLoading()
    }
  },

  onClose: function (e) {
    const id = e.currentTarget.dataset.id
    const title = e.currentTarget.dataset.title
    const self = this
    wx.showModal({
      title: '关闭任务',
      content: '关闭后不再计入应提交，历史录入保留。确定关闭「' + title + '」？',
      success: async function (res) {
        if (!res.confirm) return
        wx.showLoading({ title: '处理中' })
        try {
          await store.closeReportTask(id)
          wx.hideLoading()
          wx.showToast({ title: '任务已关闭', icon: 'success' })
          self.setData({ expandedId: '' })
          await self.loadAll(self.ctx)
        } catch (err) {
          wx.hideLoading()
          wx.showToast({ title: err.message || '关闭失败', icon: 'none' })
        }
      },
    })
  },
})
