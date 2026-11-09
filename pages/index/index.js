const session = require('../../utils/session')
const store = require('../../utils/store')
const dateUtil = require('../../utils/date')
const { validateRow } = require('../../utils/validator')

// records 页「补录 / 去修改」通过 Storage 传递目标日期（tabBar 页不能带参数跳转）
const BACKFILL_KEY = 'backfill_date'

// 日期切换后的展示态集中计算，避免 Hero / 按钮 / 状态文案各算一套
function buildDateView(date, entryExists, noTemplate) {
  const today = dateUtil.today()
  const isBackfill = date !== today
  const short = date.slice(5)
  const min = dateUtil.minEntryDate(today)
  let statusText
  if (noTemplate) {
    statusText = '当前没有生效的录入模板'
  } else if (isBackfill) {
    statusText = entryExists
      ? '补录 ' + date + ' · 已提交，可随时修改'
      : '补录 ' + date + ' · 待填写'
  } else {
    statusText = entryExists ? '今日已提交 · 可随时修改' : '今日待填写 · 30 秒搞定'
  }
  return {
    entryDate: date,
    isBackfill: isBackfill,
    minEntryDate: min,
    todayText: today,
    weekName: dateUtil.weekName(date),
    dateLabel: Number(date.slice(5, 7)) + '月' + Number(date.slice(8, 10)) + '日',
    canPrev: date > min,
    canNext: date < today,
    statusText: statusText,
    submitLabel: entryExists
      ? (isBackfill ? '更新 ' + short + ' 成果' : '更新今日成果')
      : (isBackfill ? '补录 ' + short + ' 成果' : '提交今日成果'),
  }
}

Page({
  data: {
    authState: 'checking', // checking | signed-out | ready
    loggingIn: false,
    loginError: '',
    needTeam: false,
    noTemplate: false,
    loading: true,
    memberName: '',
    role: '',
    isManager: false,
    teamName: '',
    template: null,
    templateName: '',
    templateVersion: 0,
    initialValue: null,
    entryExists: false,
    submitting: false,
    errorText: '',
    hintText: '',
    todayText: '',
    entryDate: '',
    minEntryDate: '',
    isBackfill: false,
    weekName: '',
    dateLabel: '',
    canPrev: false,
    canNext: false,
    statusText: '',
    submitLabel: '提交今日成果',
    adminLinks: [],
  },

  rowsData: null,
  ctx: null,

  onShow: async function () {
    // 每次回到首页默认展示今天；有来自记录页的补录请求时切到目标日期
    const pending = this.consumeBackfillDate()
    const date = pending || dateUtil.today()
    this.setData(Object.assign(
      { authState: 'checking', loading: true, errorText: '' },
      buildDateView(date, false, false)
    ))
    try {
      const ctx = await session.loadContext()
      if (!ctx.uid) {
        this.setData({ authState: 'signed-out', loading: false })
        return
      }
      if (!ctx.member || !ctx.team) {
        this.setData({ authState: 'ready', needTeam: true, loading: false })
        return
      }
      this.ctx = ctx
      await this.loadPage(ctx)
    } catch (e) {
      // 登录态已失效（401 已清 token）时直接回登录页，别显示空壳主界面
      if (!session.hasSession()) {
        this.setData({ authState: 'signed-out', loading: false, errorText: '' })
        return
      }
      this.setData({ authState: 'ready', loading: false, errorText: e.message || '加载失败，请下拉重试' })
    }
  },

  consumeBackfillDate: function () {
    let pending = ''
    try {
      pending = wx.getStorageSync(BACKFILL_KEY) || ''
      if (pending) wx.removeStorageSync(BACKFILL_KEY)
    } catch (e) {
      pending = ''
    }
    // 超出补录窗口的历史日期一律忽略，避免前端与服务端校验口径冲突
    return dateUtil.isEntryDateAllowed(pending) ? pending : ''
  },

  onPullDownRefresh: async function () {
    await this.onShow()
    wx.stopPullDownRefresh()
  },

  loadPage: async function (ctx) {
    const manager = session.isManager(ctx.member)
    const adminLinks = manager
      ? [
          { key: 'dashboard', title: '今日看板', desc: '提交率 / 未提交名单 / 一键催填' },
          { key: 'templates', title: '模板管理', desc: '创建 / 预览 / 发布下发模板' },
          { key: 'reports', title: '报表中心', desc: '日 / 周 / 月 / 年统计' },
          { key: 'members', title: '成员管理', desc: '角色 / 启停 / 邀请码' },
        ]
      : []
    this.setData({
      authState: 'ready',
      needTeam: false,
      loading: false,
      memberName: ctx.member.name,
      role: ctx.member.role,
      isManager: manager,
      teamName: ctx.team.name,
      adminLinks: adminLinks,
    })
    await this.loadForm(ctx)
  },

  loadForm: async function (ctx) {
    this.setData({ loading: true, errorText: '' })
    const date = this.data.entryDate || dateUtil.today()
    try {
      // 模板生效判定始终按「今天」；补录沿用当前生效模板（历史版本发布时已归档）
      const tpl = await store.getActiveTemplate(ctx.team.team_id, ctx.member)
      if (!tpl) {
        this.setData(Object.assign(
          { loading: false, noTemplate: true, template: null, initialValue: null, entryExists: false },
          buildDateView(date, false, true)
        ))
        return
      }
      const entry = await store.getMyEntry(ctx.team.team_id, date)
      let initialValue = null
      let entryExists = false
      let hintText = ''
      if (entry && entry.status === 'submitted') {
        initialValue = entry.form_data
        entryExists = true
      } else if (entry && entry.status === 'draft' && entry.template_id === tpl.template_id && entry.template_version === tpl.version) {
        initialValue = entry.form_data
      } else {
        // 草稿版本与当前模板不一致：提示按新版本重填（FR-M05 / P3-4）
        if (entry && entry.status === 'draft') {
          hintText = '模板已更新，草稿已按新版本重填（内容参考上次填写值）'
        }
        // 上次填写值记忆（按 fieldKey）
        const last = this.getLastValues(tpl, ctx)
        if (last && Object.keys(last).length > 0) {
          initialValue = [{ rowId: 'last', values: last }]
        }
      }
      this.rowsData = null
      this.setData(Object.assign({
        loading: false,
        noTemplate: false,
        template: tpl,
        templateName: tpl.name,
        templateVersion: tpl.version,
        initialValue: initialValue,
        entryExists: entryExists,
        hintText: hintText,
        errorText: '',
      }, buildDateView(date, entryExists, false)))
    } catch (e) {
      this.setData({ loading: false, errorText: e.message || '加载失败' })
    }
  },

  // ---------- 日期切换 / 补录 ----------
  onDateChange: function (e) {
    this.pickDate(e.detail.value)
  },

  shiftEntryDate: function (e) {
    const delta = Number(e.currentTarget.dataset.delta)
    this.pickDate(dateUtil.addDays(this.data.entryDate, delta))
  },

  pickDate: function (date) {
    if (!dateUtil.isEntryDateAllowed(date)) {
      wx.showToast({ title: '仅支持补录近 ' + dateUtil.BACKFILL_DAYS + ' 天', icon: 'none' })
      return
    }
    if (date === this.data.entryDate) return
    this.setData(buildDateView(date, false, false))
    if (this.ctx) this.loadForm(this.ctx)
  },

  getLastValues: function (tpl, ctx) {
    const key = 'lastValues_' + ctx.team.team_id + '_' + tpl.template_id
    try {
      return wx.getStorageSync(key) || null
    } catch (e) {
      return null
    }
  },

  saveLastValues: function (rows) {
    if (!this.ctx || !this.data.template) return
    const key = 'lastValues_' + this.ctx.team.team_id + '_' + this.data.template.template_id
    const merged = {}
    rows.forEach(function (r) {
      Object.keys(r.values).forEach(function (k) {
        const v = r.values[k]
        if (v !== '' && v !== undefined && v !== null && !(Array.isArray(v) && v.length === 0)) {
          merged[k] = v
        }
      })
    })
    try {
      wx.setStorageSync(key, merged)
    } catch (e) {
      // 存储失败不阻断主流程
    }
  },

  onFormChange: function (e) {
    this.rowsData = e.detail.rows
  },

  currentRows: function () {
    const comp = this.selectComponent('#form')
    return comp ? comp.getRows() : this.rowsData || []
  },

  onDraft: function () {
    this.save('draft')
  },

  onSubmit: function () {
    this.save('submitted')
  },

  save: async function (status) {
    if (!this.ctx || !this.data.template) return
    // 提交前比对当前生效模板（保障管理端实时调整立即生效）
    try {
      const fresh = await store.getActiveTemplate(this.ctx.team.team_id, this.ctx.member)
      if (!fresh) {
        wx.showToast({ title: '模板已停用或不再对你生效，请联系管理员', icon: 'none' })
        await this.loadForm(this.ctx)
        return
      }
      if (
        fresh.template_id !== this.data.template.template_id ||
        Number(fresh.version) !== Number(this.data.template.version)
      ) {
        wx.showToast({ title: '模板已更新，请按新模板填写', icon: 'none' })
        await this.loadForm(this.ctx)
        return
      }
    } catch (e) {
      // 提交必须确认模板未变更；草稿允许离线暂存（服务端会再复核一次）
      if (status === 'submitted') {
        wx.showToast({ title: '无法确认当前模板，请检查网络后重试', icon: 'none' })
        return
      }
    }
    const rows = this.currentRows()
    if (status === 'submitted') {
      const fields = this.data.template.fields || []
      const errors = []
      for (let i = 0; i < rows.length; i++) {
        const errs = validateRow(rows[i].values, fields)
        if (errs) {
          Object.keys(errs).forEach(function (k) {
            errors.push('第' + (i + 1) + '条：' + errs[k])
          })
        }
      }
      if (errors.length > 0) {
        this.setData({ errorText: errors[0] })
        wx.showToast({ title: errors[0], icon: 'none' })
        return
      }
    }
    const date = this.data.entryDate || dateUtil.today()
    const isBackfill = this.data.isBackfill
    this.setData({ submitting: true, errorText: '' })
    try {
      await store.saveEntry({
        team_id: this.ctx.team.team_id,
        entry_date: date,
        template_id: this.data.template.template_id,
        template_version: this.data.template.version,
        form_data: rows,
        status: status,
        source: isBackfill ? 'backfill' : 'manual',
        updated_at: new Date().toISOString(),
      })
      if (status === 'submitted') {
        this.saveLastValues(rows)
        store.logAction(this.ctx.team.team_id, 'entry_submit', 'daily_entries', this.data.template.template_id, {
          date: date,
          rows: rows.length,
          backfill: isBackfill,
        })
        wx.showToast({ title: isBackfill ? '已补录 ' + date.slice(5) : '已提交今日成果', icon: 'success' })
        this.setData({ hintText: '' })
      } else {
        wx.showToast({ title: isBackfill ? '补录草稿已保存' : '草稿已保存', icon: 'success' })
      }
      await this.loadForm(this.ctx)
    } catch (e) {
      wx.showToast({ title: e.message || '保存失败', icon: 'none' })
    }
    this.setData({ submitting: false })
  },

  // ---------- 登录 ----------
  onWechatLogin: async function () {
    this.setData({ loggingIn: true, loginError: '' })
    try {
      await session.login()
      this.setData({ loggingIn: false })
      this.onShow()
    } catch (e) {
      this.setData({ loggingIn: false, loginError: (e && e.message) || '微信登录失败，请重试' })
    }
  },

  goTeam: function () {
    wx.navigateTo({ url: '/pages/team/team' })
  },

  onAdminTap: function (e) {
    const key = e.currentTarget.dataset.key
    const urls = {
      dashboard: '/pages/admin/dashboard/dashboard',
      templates: '/pages/admin/templates/templates',
      reports: '/pages/admin/reports/reports',
      members: '/pages/admin/members/members',
    }
    if (urls[key]) wx.navigateTo({ url: urls[key] })
  },
})
