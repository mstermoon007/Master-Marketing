const session = require('../../utils/session')
const store = require('../../utils/store')
const dateUtil = require('../../utils/date')

// 与首页约定的跨页参数（tabBar 页不支持 URL 传参）
const BACKFILL_KEY = 'backfill_date'

Page({
  data: {
    authState: 'checking',
    needTeam: false,
    loading: true,
    errorText: '',
    records: [],
    allRecords: [],
    backfillDays: dateUtil.BACKFILL_DAYS,
    // 筛选条件
    statusFilter: 'all', // all | submitted | draft
    rangeFilter: '30', // 7 | 30 | all
    templateFilter: 'all',
    templateOptions: [{ id: 'all', name: '全部模板' }],
    templateIndex: 0,
    hasTemplateFilter: false,
    filteredCount: 0,
  },

  onShow: async function () {
    this.setData({ authState: 'checking', loading: true, errorText: '' })
    try {
      const ctx = await session.loadContext()
      if (!ctx.uid) {
        // index 是 tabBar 页，必须用 switchTab；同时复位 loading 避免卡在「加载中…」
        this.setData({ loading: false })
        wx.switchTab({ url: '/pages/index/index' })
        return
      }
      if (!ctx.member || !ctx.team) {
        this.setData({ authState: 'ready', needTeam: true, loading: false })
        return
      }
      await this.loadRecords(ctx)
    } catch (e) {
      if (!session.hasSession()) {
        this.setData({ loading: false })
        wx.switchTab({ url: '/pages/index/index' })
        return
      }
      this.setData({ authState: 'ready', loading: false, errorText: e.message || '加载失败' })
    }
  },

  loadRecords: async function (ctx) {
    try {
      const entries = await store.listMyEntries(ctx.team.team_id, 60)
      const nameMap = await this.loadTemplateNames(ctx.team.team_id)
      const records = entries.map(function (en) {
        // 用本地时区解析 created_at，避免 UTC 截断造成假"补录"（P2-1）
        let createdDay = ''
        try {
          createdDay = en.created_at ? dateUtil.fmtDate(new Date(en.created_at)) : ''
        } catch (e) {
          createdDay = ''
        }
        return {
          id: en.id,
          date: en.entry_date,
          status: en.status,
          statusText: en.status === 'submitted' ? '已提交' : '草稿',
          statusClass: en.status === 'submitted' ? 'tag-ok' : 'tag-warn',
          rowCount: (en.form_data || []).length,
          backfill: createdDay && createdDay !== en.entry_date,
          firstValue: firstRowText(en),
          templateId: en.template_id || '',
          templateName: nameMap[en.template_id] || '未命名模板',
        }
      })
      this.setData({
        authState: 'ready',
        needTeam: false,
        loading: false,
        allRecords: records,
        errorText: '',
      })
      this.buildTemplateOptions(records)
      this.applyFilters()
    } catch (e) {
      if (!session.hasSession()) {
        this.setData({ loading: false })
        wx.switchTab({ url: '/pages/index/index' })
        return
      }
      this.setData({ loading: false, errorText: e.message || '加载失败' })
    }
  },

  // 模板名映射：普通成员也能读 listTemplates，用于历史记录归类
  loadTemplateNames: async function (teamId) {
    try {
      const list = await store.listTemplates(teamId)
      const map = {}
      ;(list || []).forEach(function (t) {
        const prev = map[t.template_id]
        // 同一模板多版本时优先展示最高版本的名称
        if (!prev || Number(t.version) > Number(prev.version)) map[t.template_id] = t
      })
      const names = {}
      Object.keys(map).forEach(function (id) {
        names[id] = map[id].name
      })
      return names
    } catch (e) {
      return {}
    }
  },

  buildTemplateOptions: function (records) {
    const seen = {}
    const options = [{ id: 'all', name: '全部模板' }]
    records.forEach(function (r) {
      if (!r.templateId || seen[r.templateId]) return
      seen[r.templateId] = true
      options.push({ id: r.templateId, name: r.templateName })
    })
    this.setData({
      templateOptions: options,
      hasTemplateFilter: options.length > 2,
      templateFilter: 'all',
      templateIndex: 0,
    })
  },

  applyFilters: function () {
    const { allRecords, statusFilter, rangeFilter, templateFilter } = this.data
    const today = dateUtil.today()
    let cutoff = ''
    if (rangeFilter !== 'all') {
      cutoff = dateUtil.addDays(today, -(Number(rangeFilter) - 1))
    }
    const filtered = allRecords.filter(function (r) {
      if (statusFilter !== 'all' && r.status !== statusFilter) return false
      if (templateFilter !== 'all' && r.templateId !== templateFilter) return false
      if (cutoff && r.date < cutoff) return false
      return true
    })
    this.setData({ records: filtered, filteredCount: filtered.length })
  },

  onStatusFilter: function (e) {
    this.setData({ statusFilter: e.currentTarget.dataset.value })
    this.applyFilters()
  },

  onRangeFilter: function (e) {
    this.setData({ rangeFilter: e.currentTarget.dataset.value })
    this.applyFilters()
  },

  onTemplateFilter: function (e) {
    const idx = Number(e.detail.value)
    const opt = this.data.templateOptions[idx] || { id: 'all' }
    this.setData({ templateIndex: idx, templateFilter: opt.id })
    this.applyFilters()
  },

  goToday: function () {
    wx.switchTab({ url: '/pages/index/index' })
  },

  // 跳到首页并把日期切到指定日；超出补录窗口时由首页自动忽略
  goEntryDate: function (date) {
    if (!dateUtil.isEntryDateAllowed(date)) {
      wx.showToast({ title: '仅支持补录近 ' + dateUtil.BACKFILL_DAYS + ' 天', icon: 'none' })
      return
    }
    try {
      wx.setStorageSync(BACKFILL_KEY, date)
    } catch (e) {
      wx.showToast({ title: '本地存储不可用，请在首页手动选择日期', icon: 'none' })
      return
    }
    wx.switchTab({ url: '/pages/index/index' })
  },

  // 漏填某天时，列表里没有该天的记录可点，因此提供独立的补录入口（默认昨天）
  onBackfill: function () {
    this.goEntryDate(dateUtil.addDays(dateUtil.today(), -1))
  },

  onEditDate: function (e) {
    this.goEntryDate(e.currentTarget.dataset.date)
  },
})

function firstRowText(entry) {
  const rows = entry.form_data || []
  if (!rows.length) return ''
  const values = rows[0].values || {}
  const keys = Object.keys(values)
  if (!keys.length) return ''
  let text = ''
  keys.some(function (k) {
    const v = values[k]
    if (v && typeof v === 'string') {
      text = v
      return true
    }
    return false
  })
  return text.slice(0, 40)
}
