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
      const row = await store.publishTemplate(id)
      const effective = row && row.effective_from ? row.effective_from : '今天'
      wx.showToast({ title: '已发布 v' + row.version + '，' + effective + ' 起生效', icon: 'none' })
      this.onShow()
    } catch (e) {
      wx.showToast({ title: e.message || '发布失败', icon: 'none' })
    }
  },

  onArchive: async function (e) {
    const id = e.currentTarget.dataset.id
    const self = this
    // 旧版本在发布新版本时已归档，停用并不会「回退到上一生效版本」；
    // 按实际剩余的已生效模板数量给出准确提示，避免管理员误判后果。
    let content = '停用后该模板不再对成员下发。确认停用？'
    try {
      const ctx = await session.loadContext()
      if (ctx && ctx.team) {
        const rows = await store.listTemplates(ctx.team.team_id)
        const today = require('../../../utils/date').today()
        const others = (rows || []).filter(function (t) {
          return t.status === 'published' &&
            String(t.id) !== String(id) &&
            (!t.effective_from || t.effective_from <= today)
        })
        content = others.length
          ? '停用后成员端将改用其它已生效模板（' + others.length + ' 个）。确认停用？'
          : '停用后若没有其他已发布模板，成员端将提示「暂无生效模板」。确认停用？'
      }
    } catch (err) {
      // 列表读取失败不阻断停用，使用中性文案
    }
    wx.showModal({
      title: '停用模板',
      content: content,
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
