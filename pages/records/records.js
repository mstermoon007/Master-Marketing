const session = require('../../utils/session')
const store = require('../../utils/store')

Page({
  data: {
    authState: 'checking',
    needTeam: false,
    loading: true,
    errorText: '',
    records: [],
  },

  onShow: async function () {
    this.setData({ authState: 'checking', loading: true, errorText: '' })
    try {
      const ctx = await session.loadContext()
      if (!ctx.uid) {
        wx.navigateTo({ url: '/pages/index/index' })
        return
      }
      if (!ctx.member || !ctx.team) {
        this.setData({ authState: 'ready', needTeam: true, loading: false })
        return
      }
      await this.loadRecords(ctx)
    } catch (e) {
      this.setData({ authState: 'ready', loading: false, errorText: e.message || '加载失败' })
    }
  },

  loadRecords: async function (ctx) {
    try {
      const entries = await store.listMyEntries(ctx.team.team_id, ctx.member.user_id, 60)
      const dateUtil = require('../../utils/date')
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
      this.setData({ loading: false, errorText: e.message || '加载失败' })
    }
  },

  goToday: function () {
    wx.switchTab({ url: '/pages/index/index' })
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
