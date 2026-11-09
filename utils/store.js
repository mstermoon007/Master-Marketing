// 数据访问层：teams / members / form_templates / daily_entries / audit_logs
// 经自有服务端 /api 访问；本层保持 action 契约，页面零改动。
// 身份一律由服务端验签 JWT 得出，客户端不传 uid/userId（防伪造）。
const { callApi } = require('./http')

// ---------- 团队 ----------
// 真实身份由服务端验签 JWT 得出，客户端不传 uid
async function createTeam(name, memberName) {
  return callApi('createTeam', { name: name, memberName: memberName })
}

async function findTeamByCode(code) {
  return callApi('findTeam', { code: code })
}

async function joinTeam(teamId, memberName) {
  return callApi('joinTeam', { teamId: teamId, memberName: memberName })
}

async function getTeam(teamId) {
  return callApi('getTeam', { teamId: teamId })
}

async function updateTeamConfig(teamId, config) {
  return callApi('updateTeamConfig', { teamId: teamId, config: config })
}

// ---------- 成员 ----------
async function getMyMember() {
  return callApi('getMyMember')
}

async function listMembers(teamId) {
  return callApi('listMembers', { teamId: teamId })
}

async function updateMember(id, patch) {
  return callApi('updateMember', { id: id, patch: patch })
}

async function removeMember(id) {
  return callApi('removeMember', { id: id })
}

// ---------- 模板 ----------
async function listTemplates(teamId) {
  return callApi('listTemplates', { teamId: teamId })
}

async function getTemplate(id) {
  return callApi('getTemplate', { id: id })
}

async function listPublishedTemplates(teamId) {
  return callApi('listPublishedTemplates', { teamId: teamId })
}

async function createDraft(payload) {
  return callApi('createDraft', { payload: payload })
}

async function updateTemplateRow(id, patch) {
  return callApi('updateTemplateRow', { id: id, patch: patch })
}

async function deleteTemplateRow(id) {
  return callApi('deleteTemplateRow', { id: id })
}

async function nextVersion(teamId, templateId) {
  return callApi('nextVersion', { teamId: teamId, templateId: templateId })
}

// 发布模板（管理端"随时调整"的统一入口）：
// 服务端完成 草稿 → published → 归档旧版本 → 冻结快照写审计
async function publishTemplate(id) {
  const dateUtil = require('./date')
  return callApi('publishTemplate', { id: id, today: dateUtil.today() })
}

function sortTemplates(a, b) {
  if (a.effective_from === b.effective_from) return Number(b.version) - Number(a.version)
  return (b.effective_from || '') > (a.effective_from || '') ? 1 : -1
}

// 当前所有已生效的已发布模板，按「生效日 → 版本」降序。
// 管理端算「应提交名单」必须遍历全部模板，不能只取最新一个（多模板分别下发时会漏人）。
async function getEffectiveTemplates(teamId, asOf) {
  const list = await listPublishedTemplates(teamId)
  const day = asOf || require('./date').today()
  return (list || []).filter(function (t) {
    return !t.effective_from || t.effective_from <= day
  }).sort(sortTemplates)
}

// 成员端：从已生效模板里取第一个命中该成员下发范围的（一天一条记录）
async function getActiveTemplate(teamId, member, asOf) {
  const candidates = await getEffectiveTemplates(teamId, asOf)
  for (let i = 0; i < candidates.length; i++) {
    if (inScope(candidates[i].scope, member)) return candidates[i]
  }
  return null
}

function inScope(scope, member) {
  if (!scope || !scope.type || scope.type === 'all') return true
  if (!member) return false
  if (scope.type === 'members') {
    return (scope.memberIds || []).indexOf(member.user_id) >= 0
  }
  if (scope.type === 'roles') {
    return (scope.roles || []).indexOf(member.role) >= 0
  }
  return true
}

// 管理端「应提交」口径：命中任意一个已生效模板的范围即应提交。
// 无生效模板时沿用旧行为（全员计入口径），页面用 hasTemplate 单独提示。
function inAnyScope(templates, member) {
  if (!templates || templates.length === 0) return true
  return templates.some(function (t) {
    return inScope(t.scope, member)
  })
}

// ---------- 录入 ----------
async function getMyEntry(teamId, date) {
  return callApi('getMyEntry', { teamId: teamId, date: date })
}

// 幂等 upsert（team_id + user_id + entry_date），user_id 以服务端 JWT 身份为准
async function saveEntry(payload) {
  return callApi('saveEntry', { payload: payload })
}

async function listMyEntries(teamId, limit) {
  return callApi('listMyEntries', { teamId: teamId, limit: limit || 60 })
}

// 服务端单次最多返回 1000 条。此处自动翻页拉全，页面仍按「数组」消费，零改动；
// 超过硬上限时明确报错，绝不静默截断导致年报表少算数据。
const TEAM_ENTRIES_PAGE_SIZE = 1000
const TEAM_ENTRIES_MAX_PAGES = 50

async function listTeamEntries(teamId, from, to) {
  const all = []
  for (let page = 0; page < TEAM_ENTRIES_MAX_PAGES; page++) {
    const batch = await callApi('listTeamEntries', {
      teamId: teamId,
      from: from,
      to: to,
      page: page,
      pageSize: TEAM_ENTRIES_PAGE_SIZE,
    })
    const rows = Array.isArray(batch) ? batch : []
    all.push.apply(all, rows)
    if (rows.length < TEAM_ENTRIES_PAGE_SIZE) return all
  }
  throw new Error('数据量过大，请缩小统计周期后重试')
}

// ---------- 审计 ----------
async function logAction(teamId, action, targetType, targetId, detail) {
  try {
    await callApi('log', {
      teamId: teamId,
      action: action,
      targetType: targetType || null,
      targetId: targetId ? String(targetId) : null,
      detail: detail || null,
    })
  } catch (e) {
    // 审计失败不阻断主流程
  }
}

module.exports = {
  createTeam,
  findTeamByCode,
  joinTeam,
  getTeam,
  updateTeamConfig,
  getMyMember,
  listMembers,
  updateMember,
  removeMember,
  listTemplates,
  getTemplate,
  listPublishedTemplates,
  createDraft,
  updateTemplateRow,
  deleteTemplateRow,
  publishTemplate,
  nextVersion,
  getActiveTemplate,
  getEffectiveTemplates,
  inScope,
  inAnyScope,
  getMyEntry,
  saveEntry,
  listMyEntries,
  listTeamEntries,
  logAction,
}
