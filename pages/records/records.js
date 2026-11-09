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
    backfillDays: dateUtil.BACKFILL_DAYS,
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
        }
      })
      this.setData({ authState: 'ready', needTeam: false, loading: false, records: records, errorText: '' })
    } catch (e) {
      if (!session.hasSession()) {
        this.setData({ loading: false })
        wx.switchTab({ url: '/pages/index/index' })
        return
      }
      this.setData({ loading: false, errorText: e.message || '加载失败' })
    }
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
