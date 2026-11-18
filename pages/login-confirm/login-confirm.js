const session = require('../../utils/session')
const store = require('../../utils/store')

Page({
  data: {
    state: 'checking',
    ticket: '',
    message: '',
    workspaces: [],
  },

  onLoad: function (options) {
    let scene = (options && options.scene) || ''
    try {
      scene = decodeURIComponent(scene)
    } catch (e) {
      // 保持原始值
    }
    scene = String(scene || '').trim()
    if (!/^[0-9a-f]{32}$/.test(scene)) {
      this.setData({ state: 'error', message: '二维码无效，请在网页端重新生成' })
      return
    }
    this.setData({ ticket: scene, state: 'ready' })
  },

  confirm: async function () {
    if (this.data.state === 'loading' || this.data.state === 'success') return
    this.setData({ state: 'loading', message: '' })
    try {
      if (!session.hasSession()) await session.login()
      const result = await store.confirmWebLogin(this.data.ticket)
      this.setData({
        state: 'success',
        workspaces: (result && result.workspaces) || [],
      })
    } catch (e) {
      this.setData({
        state: 'error',
        message: (e && e.message) || '确认登录失败，请重试',
      })
    }
  },

  retry: function () {
    this.setData({ state: 'ready', message: '' })
  },

  backHome: function () {
    wx.switchTab({ url: '/pages/index/index' })
  },
})
