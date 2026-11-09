const { cloud } = require('./utils/cloud')

App({
  globalData: {
    appName: '今日报数',
    uid: null,
    member: null,
    team: null,
  },
  onShow(options) {
    // 登录回调统一入口：WorkBuddy 授权回跳 / 普通启动都会走这里
    this.authReady = (async () => {
      const callback = await cloud.auth.handleWorkBuddyMiniProgramCallback(options)
      if (callback && callback.error) return callback
      return cloud.auth.getSession()
    })()
  },
})
