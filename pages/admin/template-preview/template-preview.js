const session = require('../../../utils/session')
const store = require('../../../utils/store')

Page({
  data: {
    loading: true,
    errorText: '',
    template: null,
    tplName: '',
    statusText: '',
  },

  onLoad: function (options) {
    this.templateId = options && options.id ? options.id : null
  },

  onShow: async function () {
    this.setData({ loading: true, errorText: '' })
    try {
      const ctx = await session.loadContext()
      if (!ctx.member || !ctx.team) {
        wx.switchTab({ url: '/pages/index/index' })
        return
      }
      if (!this.templateId) {
        this.setData({ loading: false, errorText: '缺少模板参数' })
        return
      }
      // 服务端同样会校验（草稿仅管理员可读），这里先拦截避免普通成员白等一次请求
      if (!session.isManager(ctx.member)) {
        this.setData({ loading: false, errorText: '仅管理员 / 负责人可预览模板' })
        return
      }
      const row = await store.getTemplate(this.templateId)
      if (!row) {
        this.setData({ loading: false, errorText: '模板不存在' })
        return
      }
      this.setData({
        loading: false,
        template: row,
        tplName: row.name,
        statusText: row.status === 'draft' ? '草稿预览（成员端将按此渲染）' : 'v' + row.version,
      })
    } catch (e) {
      this.setData({ loading: false, errorText: e.message || '加载失败' })
    }
  },
})
