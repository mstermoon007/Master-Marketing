// 自有服务端地址配置
// 并在「微信公众平台 → 开发 → 开发管理 → 服务器域名」把该域名加入 request 合法域名。
// 注意：小程序 request 不接受 IP / localhost，真机必须 HTTPS + 已备案域名。
const RELEASE_BASE = 'https://api.modouyu.top'
const DEV_BASE = 'https://api.modouyu.top'

function envVersion() {
  try {
    const info = wx.getAccountInfoSync()
    return (info && info.miniProgram && info.miniProgram.envVersion) || 'release'
  } catch (e) {
    return 'release'
  }
}

const base = envVersion() === 'release' ? RELEASE_BASE : DEV_BASE

// 占位域名未替换时给出可诊断的提示，避免只报「网络连接失败」
const isPlaceholder = /example\.com/i.test(base)

module.exports = {
  BASE_URL: base,
  REQUEST_TIMEOUT: 15000,
  IS_PLACEHOLDER: isPlaceholder,
}
