const session = require('../../../utils/session')
const store = require('../../../utils/store')
const dateUtil = require('../../../utils/date')
const stats = require('../../../utils/stats')

const PERIOD_OPTIONS = [
  { value: 'day', label: '日' },
  { value: 'week', label: '周' },
  { value: 'month', label: '月' },
  { value: 'year', label: '年' },
]
const PERIOD_LABELS = PERIOD_OPTIONS.map(function (o) {
  return o.label
})

// 本地时区日期偏移（dstr: YYYY-MM-DD, delta 天数）
function shiftDay(dstr, delta) {
  const d = new Date(dstr + 'T00:00:00')
  d.setDate(d.getDate() + delta)
  const p = function (n) {
    return (n < 10 ? '0' : '') + n
  }
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate())
}

Page({
  data: {
    loading: true,
    denied: false,
    errorText: '',
    periodOptions: PERIOD_LABELS,
    periodIndex: 0,
    date: '',
    rangeText: '',
    hasData: false,
    hasTemplate: false,
    summary: null,
    fields: [],
    memberRows: [],
    trendTitle: '',
    trend: [],
    rankTitle: '',
    memberRank: [],
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
      this.ctx = ctx
      if (!this.data.date) {
        this.setData({ date: dateUtil.today() })
      }
      await this.loadReport()
    } catch (e) {
      this.setData({ loading: false, errorText: e.message || '加载失败' })
    }
  },

  onPeriod: async function (e) {
    const opt = PERIOD_OPTIONS[Number(e.detail.value)]
    this.setData({ periodIndex: Number(e.detail.value) })
    this.periodValue = opt.value
    await this.loadReport()
  },

  onDate: async function (e) {
    this.setData({ date: e.detail.value })
    await this.loadReport()
  },

  loadReport: async function () {
    this.setData({ loading: true, errorText: '' })
    try {
      const ctx = this.ctx
      const period = this.periodValue || 'day'
      const date = this.data.date
      const range = dateUtil.rangeOf(period, date)
      this.setData({ rangeText: dateUtil.periodLabel(period, date) })
      // 忽略查询者自身范围：以模板下发范围为准，逐成员判定（P1-2）
      const tpl = await store.getActiveTemplate(ctx.team.team_id, ctx.member, true)
      const entries = await store.listTeamEntries(ctx.team.team_id, range[0], range[1])
      const members = await store.listMembers(ctx.team.team_id)
      const nameMap = {}
      members.forEach(function (m) {
        nameMap[m.user_id] = m.name
      })

      // 应提交范围：按模板 scope 逐成员判定
      let targets = members.filter(function (m) {
        return m.status === 'active' && (!tpl || store.inScope(tpl.scope, m))
      })

      // 跨版本合并（P1-4）：每个 entry 按其所属模板版本的字段定义聚合，按 fieldKey 合并
      const allTemplates = await store.listTemplates(ctx.team.team_id)
      const fieldsMap = {}
      allTemplates.forEach(function (t) {
        fieldsMap[t.template_id + ':' + t.version] = t.fields || []
      })
      const currentFields = tpl ? tpl.fields || [] : []
      const result = stats.aggregateEntriesMulti(entries, function (entry) {
        const key = entry.template_id + ':' + entry.template_version
        return fieldsMap[key] || currentFields
      })

      // 已提交人数（按 user 去重）与提交率（P1-1）
      const submittedUsers = {}
      entries.forEach(function (en) {
        if (en.status === 'submitted') submittedUsers[en.user_id] = true
      })
      const submittedUserCount = Object.keys(submittedUsers).filter(function (uid) {
        const m = members.filter(function (x) {
          return x.user_id === uid
        })[0]
        return m && m.status === 'active' && (!tpl || store.inScope(tpl.scope, m))
      }).length

      const aggByUser = result.byUser
      const fieldDefs = result.fields
      const memberRows = targets.map(function (m) {
        const agg = aggByUser[m.user_id]
        const cells = fieldDefs.map(function (fd) {
          if (!agg) return { label: fd.label, text: '-' }
          const uf = agg.fields[fd.fieldKey]
          const v = uf ? stats.displayValue(uf, fd.method) : 0
          return { label: fd.label, text: String(v) }
        })
        return {
          userId: m.user_id,
          name: m.name,
          submitted: !!(agg && agg.submitted),
          rowCount: agg ? agg.rowCount : 0,
          cells: cells,
        }
      })

      // 聚合字段合计的条形宽度（以最大值为 100%）
      let maxVal = 0
      const fieldBars = fieldDefs.map(function (fd) {
        const v = stats.displayValue(fd, fd.method)
        if (v > maxVal) maxVal = v
        return { fieldKey: fd.fieldKey, label: fd.label, unit: fd.unit, method: fd.method, value: v, percent: 0 }
      })
      fieldBars.forEach(function (b) {
        b.percent = maxVal > 0 ? Math.round((b.value / maxVal) * 100) : 0
      })

      // ---------- 图表 1：近 7 日趋势柱状图 ----------
      // 主指标：优先第一个聚合字段（业务核心数值），否则用成果条数
      const mainField = fieldDefs.length > 0 ? fieldDefs[0] : null
      const trendToday = dateUtil.today()
      const trendStart = shiftDay(trendToday, -6)
      let trendEntries = entries
      if (range[0] !== trendStart || range[1] !== trendToday) {
        trendEntries = await store.listTeamEntries(ctx.team.team_id, trendStart, trendToday)
      }
      // 按日分组（仅 submitted）
      const byDay = {}
      trendEntries.forEach(function (en) {
        if (en.status !== 'submitted' || !en.entry_date) return
        const d = en.entry_date
        if (!byDay[d]) byDay[d] = { rows: 0, users: {} }
        const rows = en.form_data || []
        byDay[d].rows += rows.length
        byDay[d].users[en.user_id] = true
        if (mainField) {
          rows.forEach(function (row) {
            const raw = (row.values || {})[mainField.fieldKey]
            const n = parseFloat(raw)
            if (mainField.method === 'count') {
              byDay[d].fieldVal = (byDay[d].fieldVal || 0) + (raw !== undefined && raw !== null && raw !== '' ? 1 : 0)
            } else if (!isNaN(n)) {
              byDay[d].fieldVal = (byDay[d].fieldVal || 0) + n
            }
          })
        }
      })
      const trend = []
      let trendMax = 0
      for (let i = 6; i >= 0; i--) {
        const d = shiftDay(trendToday, -i)
        const info = byDay[d] || { rows: 0, users: {} }
        const v = mainField
          ? Math.round((info.fieldVal || 0) * 100) / 100
          : info.rows
        if (v > trendMax) trendMax = v
        trend.push({
          dateLabel: d.slice(5),
          value: v,
          users: Object.keys(info.users).length,
          h: 0,
        })
      }
      trend.forEach(function (t) {
        t.h = trendMax > 0 ? Math.max(6, Math.round((t.value / trendMax) * 100)) : 6
      })

      // ---------- 图表 2：成员对比排名（主指标横向条形） ----------
      let memberRank = []
      if (mainField && targets.length > 0) {
        memberRank = targets
          .map(function (m) {
            const agg = aggByUser[m.user_id]
            const uf = agg ? agg.fields[mainField.fieldKey] : null
            const v = uf ? stats.displayValue(uf, mainField.method) : 0
            return { name: m.name, value: v, unit: mainField.unit || '', percent: 0, submitted: !!(agg && agg.submitted) }
          })
          .sort(function (a, b) {
            return b.value - a.value
          })
        let rMax = 0
        memberRank.forEach(function (r) {
          if (r.value > rMax) rMax = r.value
        })
        memberRank.forEach(function (r, i) {
          r.percent = rMax > 0 ? Math.round((r.value / rMax) * 100) : 0
          r.rank = i + 1
          r.top = i < 3
        })
      }

      const should = targets.length
      const rate = should > 0 ? Math.min(100, Math.round((submittedUserCount / should) * 100)) : 0
      this.setData({
        loading: false,
        hasData: entries.length > 0,
        hasTemplate: !!tpl,
        summary: {
          entryCount: result.entryCount,
          rowCount: result.rowCount,
          submittedCount: submittedUserCount,
          shouldCount: should,
          rateText: rate + '%',
        },
        fields: fieldBars,
        memberRows: memberRows,
        trendTitle: mainField
          ? '近 7 日「' + mainField.label + '」趋势'
          : '近 7 日成果条数趋势',
        trend: trend,
        rankTitle: mainField
          ? '成员对比 · ' + mainField.label
          : '',
        memberRank: memberRank,
      })
    } catch (e) {
      this.setData({ loading: false, errorText: e.message || '加载失败' })
    }
  },
})
