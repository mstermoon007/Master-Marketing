// 会话与身份：code -> 自有服务端 JWT -> 成员身份 -> 团队
// 安全说明：本地只保存 token 与 openid 展示值；openid 不作为鉴权凭证，
// 所有 /api 请求的身份由服务端验签 JWT 的 sub 决定（客户端无法伪造）。
const http = require('./http')
const store = require('./store')

const UID_KEY = 'auth_openid'
// 当前选中的团队（P4 一人多空间）：只存 team_id，切换时交给服务端校验归属
const ACTIVE_TEAM_KEY = 'active_team_id'
let memoryUid = null // 存储不可用时的本次会话兜底

function currentUid() {
  try {
    return wx.getStorageSync(UID_KEY) || memoryUid
  } catch (e) {
    return memoryUid
  }
}

function getActiveTeamId() {
  try {
    return wx.getStorageSync(ACTIVE_TEAM_KEY) || ''
  } catch (e) {
    return ''
  }
}

function setActiveTeamId(teamId) {
  try {
    if (teamId) wx.setStorageSync(ACTIVE_TEAM_KEY, teamId)
    else wx.removeStorageSync(ACTIVE_TEAM_KEY)
  } catch (e) {
    // 存储失败不阻断：本次会话仍按返回值工作
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

// 把服务端 switchWorkspace 的结果写入 globalData，并返回页面消费的上下文。
// shape: { uid, session, member, team, workspace, workspaceRole, teams, departments }
function applyContext(uid, res) {
  const app = getApp()
  const data = res || {}
  const member = data.member || null
  const team = data.team || null
  const workspace = data.workspace || null
  const workspaceRole = data.workspaceRole || null
  const teams = data.teams || []
  const departments = data.departments || []
  if (app) {
    app.globalData.uid = uid
    app.globalData.member = member
    app.globalData.team = team
    app.globalData.workspace = workspace
    app.globalData.workspaceRole = workspaceRole
    app.globalData.teams = teams
    app.globalData.departments = departments
    app.globalData.loaded = true
  }
  if (team && team.team_id) setActiveTeamId(team.team_id)
  return {
    uid: uid,
    session: { openid: uid },
    member: member,
    team: team,
    workspace: workspace,
    workspaceRole: workspaceRole,
    teams: teams,
    departments: departments,
  }
}

function emptyContext(uid) {
  return {
    uid: uid || null,
    session: uid ? { openid: uid } : null,
    member: null,
    team: null,
    workspace: null,
    workspaceRole: null,
    teams: [],
    departments: [],
  }
}

// 返回 { uid, session, member, team, workspace, workspaceRole, teams, departments }
// 未登录返回 { uid: null }；当前团队来自本地缓存，失效时自动回退到默认空间。
async function loadContext(force) {
  const app = getApp()
  const uid = hasSession() ? currentUid() : null
  if (!uid) {
    clearContext()
    return emptyContext(null)
  }
  if (!force && app && app.globalData.uid === uid && app.globalData.loaded) {
    return {
      uid: uid,
      session: { openid: uid },
      member: app.globalData.member || null,
      team: app.globalData.team || null,
      workspace: app.globalData.workspace || null,
      workspaceRole: app.globalData.workspaceRole || null,
      teams: app.globalData.teams || [],
      departments: app.globalData.departments || [],
    }
  }
  const activeTeamId = getActiveTeamId()
  let res
  try {
    res = await store.switchWorkspace(activeTeamId ? { teamId: activeTeamId } : {})
  } catch (e) {
    // 缓存的团队已失效（被移除/团队解散）：清缓存后回到默认空间
    if (!activeTeamId) throw e
    setActiveTeamId('')
    res = await store.switchWorkspace({})
  }
  return applyContext(uid, res)
}

// 切换到指定团队（写入本地缓存并刷新上下文）
async function switchTeam(teamId) {
  const uid = currentUid()
  const res = await store.switchWorkspace({ teamId: teamId })
  setActiveTeamId(res && res.team ? res.team.team_id : '')
  return applyContext(uid, res)
}

// 切换工作空间：进入该空间默认团队（无团队时 team 为 null）
async function switchSpace(workspaceId) {
  const uid = currentUid()
  const res = await store.switchWorkspace({ workspaceId: workspaceId })
  setActiveTeamId(res && res.team ? res.team.team_id : '')
  return applyContext(uid, res)
}

function clearContext() {
  const app = getApp()
  if (app) {
    app.globalData.uid = null
    app.globalData.member = null
    app.globalData.team = null
    app.globalData.workspace = null
    app.globalData.workspaceRole = null
    app.globalData.teams = []
    app.globalData.departments = []
    app.globalData.loaded = false
  }
}

async function signOut() {
  http.clearToken()
  memoryUid = null
  try {
    wx.removeStorageSync(UID_KEY)
    wx.removeStorageSync(ACTIVE_TEAM_KEY)
  } catch (e) {
    // 忽略存储错误
  }
  clearContext()
}

// 管理入口按「有效角色」判断：团队 owner/manager，或空间 owner/admin（含部门负责人）
function isManager(member) {
  if (!member) return false
  const role = member.effective_role || member.role
  return role === 'owner' || role === 'manager' || role === 'admin'
}

// 401 时统一清理登录态并回到登录页，避免各页面停留在没有登录入口的空壳主界面
http.onUnauthorized(function () {
  signOut()
  wx.switchTab({ url: '/pages/index/index' })
})

module.exports = {
  currentUid,
  hasSession,
  login,
  loadContext,
  switchTeam,
  switchSpace,
  getActiveTeamId,
  clearContext,
  signOut,
  isManager,
}
