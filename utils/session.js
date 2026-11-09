// 会话与身份：code -> 自有服务端 JWT -> 成员身份 -> 团队
// 安全说明：本地只保存 token 与 openid 展示值；openid 不作为鉴权凭证，
// 所有 /api 请求的身份由服务端验签 JWT 的 sub 决定（客户端无法伪造）。
const http = require('./http')
const store = require('./store')

const UID_KEY = 'auth_openid'
let memoryUid = null // 存储不可用时的本次会话兜底

function currentUid() {
  try {
    return wx.getStorageSync(UID_KEY) || memoryUid
  } catch (e) {
    return memoryUid
  }
}

// 已登录判断以 token 为准（token 过期时服务端返回 401，由 clearContext 兜底）
function hasSession() {
  return !!http.getToken() && !!currentUid()
}

// 微信一键登录：wx.login -> /auth/login -> token + openid
async function login() {
  const loginRes = await new Promise(function (resolve, reject) {
    wx.login({ success: resolve, fail: reject })
  })
  if (!loginRes || !loginRes.code) {
    throw new Error('微信登录失败，请重试')
  }
  const data = await http.callLogin(loginRes.code)
  if (!data || !data.token || !data.openid) {
    throw new Error('登录未完成，请重试')
  }
  http.setToken(data.token)
  memoryUid = data.openid
  try {
    wx.setStorageSync(UID_KEY, data.openid)
  } catch (e) {
    // 存储失败不阻断（本次会话内仍可用）
  }
  const app = getApp()
  if (app) app.globalData.uid = data.openid
  return data.openid
}

// 返回 { uid, session, member, team }；未登录返回 { uid: null }
async function loadContext(force) {
  const app = getApp()
  const uid = hasSession() ? currentUid() : null
  if (!uid) {
    if (app) {
      app.globalData.uid = null
      app.globalData.member = null
      app.globalData.team = null
    }
    return { uid: null, session: null, member: null, team: null }
  }
  if (!force && app.globalData.uid === uid && app.globalData.member && app.globalData.team) {
    return { uid: uid, session: { openid: uid }, member: app.globalData.member, team: app.globalData.team }
  }
  const member = await store.getMyMember()
  let team = null
  if (member) team = await store.getTeam(member.team_id)
  app.globalData.uid = uid
  app.globalData.member = member
  app.globalData.team = team
  return { uid: uid, session: { openid: uid }, member: member, team: team }
}

function clearContext() {
  const app = getApp()
  if (app) {
    app.globalData.uid = null
    app.globalData.member = null
    app.globalData.team = null
  }
}

async function signOut() {
  http.clearToken()
  memoryUid = null
  try {
    wx.removeStorageSync(UID_KEY)
  } catch (e) {
    // 忽略存储错误
  }
  clearContext()
}

function isManager(member) {
  return !!member && (member.role === 'manager' || member.role === 'owner')
}

// 401 时统一清理登录态并回到登录页，避免各页面停留在没有登录入口的空壳主界面
http.onUnauthorized(function () {
  signOut()
  wx.switchTab({ url: '/pages/index/index' })
})

module.exports = { currentUid, hasSession, login, loadContext, clearContext, signOut, isManager }
