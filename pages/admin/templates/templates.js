const session = require('../../../utils/session')
const store = require('../../../utils/store')

Page({
  data: {
    loading: true,
    denied: false,
    errorText: '',
    groups: [],
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
      await this.loadTemplates(ctx)
    } catch (e) {
      this.setData({ loading: false, errorText: e.message || '加载失败' })
    }
  },

  loadTemplates: async function (ctx) {
    try {
      const rows = await store.listTemplates(ctx.team.team_id)
      const map = {}
      const order = []
      rows.forEach(function (t) {
        if (!map[t.template_id]) {
          map[t.template_id] = { templateId: t.template_id, name: t.name, versions: [] }
          order.push(t.template_id)
        }
        map[t.template_id].versions.push({
          id: t.id,
          version: t.version,
          status: t.status,
          statusText: t.status === 'draft' ? '草稿' : t.status === 'published' ? '已发布' : '已归档',
          statusClass: t.status === 'draft' ? 'tag-warn' : t.status === 'published' ? 'tag-ok' : 'tag-gray',
          fieldCount: (t.fields || []).length,
          effectiveFrom: t.effective_from || '',
          entryMode: t.entry_mode === 'repeatable' ? '多行' : '单条',
        })
      })
      const groups = order.map(function (id) {
        return map[id]
      })
      this.setData({ loading: false, groups: groups })
    } catch (e) {
      this.setData({ loading: false, errorText: e.message || '加载失败' })
    }
  },

  onCreate: function () {
    wx.showActionSheet({
      itemList: ['空白模板', '地产日报模板（推荐字段）'],
      success: function (res) {
        if (res.tapIndex === 0) {
          wx.navigateTo({ url: '/pages/admin/template-edit/template-edit' })
        } else {
          wx.navigateTo({ url: '/pages/admin/template-edit/template-edit?preset=estate' })
        }
      },
      fail: function () {
        // 用户取消，不跳转
      },
    })
  },

  onEdit: function (e) {
    const id = e.currentTarget.dataset.id
    wx.navigateTo({ url: '/pages/admin/template-edit/template-edit?id=' + id })
  },

  // 基于已发布版本派生新草稿版本（FR-T06：改字段 → 发布新版本）
  onNewVersion: function (e) {
    const id = e.currentTarget.dataset.id
    const row = this.findRow(id)
    if (!row) return
    wx.showModal({
      title: '发布新版本',
      content: '将基于 v' + row.version + ' 创建新草稿（沿用 fieldKey 与字段定义），编辑后发布即生成 v' + (row.version + 1) + '。确认继续？',
      success: function (res) {
        if (res.confirm) {
          wx.navigateTo({ url: '/pages/admin/template-edit/template-edit?from=' + id })
        }
      },
    })
  },

  findRow: function (id) {
    let found = null
    this.data.groups.forEach(function (g) {
      g.versions.forEach(function (v) {
        if (String(v.id) === String(id)) found = v
      })
    })
    return found
  },

  onPreview: function (e) {
    const id = e.currentTarget.dataset.id
    wx.navigateTo({ url: '/pages/admin/template-preview/template-preview?id=' + id })
  },

  onPublish: function (e) {
    const id = e.currentTarget.dataset.id
    const self = this
    wx.showModal({
      title: '发布模板',
      content: '发布后将立即对范围内成员生效，旧版本自动归档。确认发布？',
      success: async function (res) {
        if (!res.confirm) return
        await self.publishRow(id)
      },
    })
  },

  publishRow: async function (id) {
    try {
      const ctx = await session.loadContext()
      const row = await store.publishTemplate(ctx.team.team_id, id, ctx.member.user_id)
      wx.showToast({ title: '已发布 v' + row.version + '，成员端立即生效', icon: 'none' })
      this.onShow()
    } catch (e) {
      wx.showToast({ title: e.message || '发布失败', icon: 'none' })
    }
  },

  onArchive: function (e) {
    const id = e.currentTarget.dataset.id
    const self = this
    wx.showModal({
      title: '停用模板',
      content: '停用后成员端将回退到上一生效版本（如无则提示无模板）。确认停用？',
      success: async function (res) {
        if (!res.confirm) return
        try {
          await store.updateTemplateRow(id, { status: 'archived' })
          wx.showToast({ title: '已停用', icon: 'success' })
          self.onShow()
        } catch (err) {
          wx.showToast({ title: err.message || '操作失败', icon: 'none' })
        }
      },
    })
  },

  onDelete: function (e) {
    const id = e.currentTarget.dataset.id
    const self = this
    wx.showModal({
      title: '删除草稿',
      content: '仅删除该草稿版本，已发布版本不受影响。确认删除？',
      success: async function (res) {
        if (!res.confirm) return
        try {
          await store.deleteTemplateRow(id)
          wx.showToast({ title: '已删除', icon: 'success' })
          self.onShow()
        } catch (err) {
          wx.showToast({ title: err.message || '删除失败', icon: 'none' })
        }
      },
    })
  },
})
