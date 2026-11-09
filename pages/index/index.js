const { cloud } = require('../../utils/cloud')
const session = require('../../utils/session')
const store = require('../../utils/store')
const dateUtil = require('../../utils/date')
const { validateRow } = require('../../utils/validator')

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
    adminLinks: [],
  },

  rowsData: null,
  ctx: null,

  onShow: async function () {
    this.setData({ authState: 'checking', loading: true, errorText: '' })
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
      this.setData({ authState: 'ready', loading: false, errorText: e.message || '加载失败，请下拉重试' })
    }
  },

  weekText: function () {
    const names = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
    return names[new Date().getDay()]
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
      todayText: dateUtil.today(),
      weekName: this.weekText(),
      adminLinks: adminLinks,
    })
    await this.loadForm(ctx)
  },

  loadForm: async function (ctx) {
    this.setData({ loading: true, errorText: '' })
    try {
      const tpl = await store.getActiveTemplate(ctx.team.team_id, ctx.member)
      if (!tpl) {
        this.setData({ loading: false, noTemplate: true, template: null, initialValue: null })
        return
      }
      const entry = await store.getMyEntry(ctx.team.team_id, ctx.member.user_id, dateUtil.today())
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
      this.setData({
        loading: false,
        noTemplate: false,
        template: tpl,
        templateName: tpl.name,
        templateVersion: tpl.version,
        initialValue: initialValue,
        entryExists: entryExists,
        hintText: hintText,
        errorText: '',
      })
    } catch (e) {
      this.setData({ loading: false, errorText: e.message || '加载失败' })
    }
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
      // 校验失败不阻断提交（网络抖动时按当前表单继续）
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
    this.setData({ submitting: true, errorText: '' })
    try {
      await store.saveEntry({
        team_id: this.ctx.team.team_id,
        user_id: this.ctx.member.user_id,
        entry_date: dateUtil.today(),
        template_id: this.data.template.template_id,
        template_version: this.data.template.version,
        form_data: rows,
        status: status,
        source: 'manual',
        updated_at: new Date().toISOString(),
      })
      if (status === 'submitted') {
        this.saveLastValues(rows)
        store.logAction(this.ctx.team.team_id, 'entry_submit', 'daily_entries', this.data.template.template_id, {
          date: dateUtil.today(),
          rows: rows.length,
        })
        wx.showToast({ title: '已提交今日成果', icon: 'success' })
        this.setData({ hintText: '' })
      } else {
        wx.showToast({ title: '草稿已保存', icon: 'success' })
      }
      await this.loadForm(this.ctx)
    } catch (e) {
      wx.showToast({ title: e.message || '保存失败', icon: 'none' })
    }
    this.setData({ submitting: false })
  },

  // ---------- 登录 ----------
  onWechatLogin: function () {
    this.setData({ loggingIn: true, loginError: '' })
    wx.login({
      success: (res) => {
        if (!res.code) {
          this.setData({ loggingIn: false, loginError: '微信登录失败，请重试' })
          return
        }
        let appid = ''
        try {
          appid = wx.getAccountInfoSync().miniProgram.appId
        } catch (e) {
          appid = ''
        }
        cloud.auth
          .signInWithWechat(res.code, appid)
          .then(async (loginRes) => {
            if (loginRes && loginRes.error) {
              this.setData({ loggingIn: false, loginError: loginRes.error.message || '微信登录失败，请重试' })
              return
            }
            const app = getApp()
            app.authReady = cloud.auth.getSession()
            const ctx = await session.loadContext(true)
            this.setData({ loggingIn: false })
            if (!ctx.uid) {
              this.setData({ authState: 'signed-out', loginError: '登录未完成，请重试' })
              return
            }
            this.onShow()
          })
          .catch((err) => {
            this.setData({ loggingIn: false, loginError: (err && err.message) || '微信登录失败，请重试' })
          })
      },
      fail: (err) => {
        this.setData({ loggingIn: false, loginError: (err && err.errMsg) || '微信登录失败' })
      },
    })
  },

  onWorkBuddyLogin: function () {
    this.setData({ loggingIn: true, loginError: '' })
    cloud.auth
      .signInWithWorkBuddyMiniProgram({ redirectPath: 'pages/index/index' })
      .then(() => {
        this.setData({ loggingIn: false })
      })
      .catch((err) => {
        const code = err && err.code
        this.setData({ loggingIn: false, loginError: code === 'cancelled' ? '' : (err && err.message) || '登录失败' })
      })
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
