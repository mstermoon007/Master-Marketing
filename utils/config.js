// 自有服务端地址配置
// 并在「微信公众平台 → 开发 → 开发管理 → 服务器域名」把该域名加入 request 合法域名。
// 注意：小程序 request 不接受 IP / localhost，真机必须 HTTPS + 已备案域名。
const RELEASE_BASE = 'https://api.modouyu.top'
// 本地联调默认指向 docker compose 暴露的后端端口（server/docker-compose.yml 映射 8001）；
// 开发者工具需勾选「详情 → 本地设置 → 不校验合法域名」。
const DEV_BASE = 'http://127.0.0.1:8001'

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

// 微信订阅消息模板 ID 只在服务端 WX_TMPL_* 配置，小程序通过
// getSubscribeTemplates 拉取并缓存，不在此维护第二份，避免两侧漂移。

module.exports = {
  BASE_URL: base,
  REQUEST_TIMEOUT: 15000,
  IS_PLACEHOLDER: isPlaceholder,
}
