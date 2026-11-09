App({
  globalData: {
    uid: null,
    member: null,
    team: null,
  },
  onLaunch() {
    // 会话由 utils/session.js 统一管理（token 存本地，服务端验签）
    // 各页面 onShow 调用 loadContext() 时按需续期与加载身份
  },
})
