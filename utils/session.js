// 会话与身份：登录态（WorkBuddy/微信）→ 成员身份 → 团队
const { cloud } = require('./cloud')
const store = require('./store')

function getAppSafe() {
  return getApp()
}

async function ensureSession() {
  const app = getAppSafe()
  if (app && app.authReady) {
    return app.authReady
  }
  const session = await cloud.auth.getSession()
  if (app) app.authReady = Promise.resolve(session)
  return session
}

// 返回 { uid, session, member, team }；未登录返回 { uid: null }
async function loadContext(force) {
  const app = getAppSafe()
  const res = await ensureSession()
  // authReady 的返回形态：{ data: session, error }（或回调对象 { data: null, error }）
  const session = res && res.data ? res.data : null
  if (!session || !session.user || !session.user.id) {
    app.globalData.uid = null
    app.globalData.member = null
    app.globalData.team = null
    return { uid: null, session: null, member: null, team: null }
  }
  const uid = session.user.id
  if (!force && app.globalData.uid === uid && app.globalData.member && app.globalData.team) {
    return { uid: uid, session: session, member: app.globalData.member, team: app.globalData.team }
  }
  const member = await store.getMyMember(uid)
  let team = null
  if (member) team = await store.getTeam(member.team_id)
  app.globalData.uid = uid
  app.globalData.member = member
  app.globalData.team = team
  return { uid: uid, session: session, member: member, team: team }
}

function clearContext() {
  const app = getAppSafe()
  if (app) {
    app.globalData.uid = null
    app.globalData.member = null
    app.globalData.team = null
    app.authReady = null
  }
}

async function signOut() {
  try {
    await cloud.auth.signOut()
  } catch (e) {
    // 忽略退出错误
  }
  clearContext()
}

function isManager(member) {
  return !!member && (member.role === 'manager' || member.role === 'owner')
}

module.exports = { ensureSession, loadContext, clearContext, signOut, isManager }
