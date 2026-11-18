// 数据访问层：teams / members / form_templates / daily_entries / audit_logs
// 经自有服务端 /api 访问；本层保持 action 契约，页面零改动。
// 身份一律由服务端验签 JWT 得出，客户端不传 uid/userId（防伪造）。
const { callApi } = require('./http')

// ---------- 团队 ----------
// 真实身份由服务端验签 JWT 得出，客户端不传 uid
// workspaceId / departmentId 可选：不传则服务端自动创建「团队名 工作空间」
async function createTeam(name, memberName, workspaceId, departmentId) {
  return callApi('createTeam', {
    name: name,
    memberName: memberName,
    workspaceId: workspaceId || '',
    departmentId: departmentId || '',
  })
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
// teamId 可选：一人多空间时用于定位当前团队下的成员行
async function getMyMember(teamId) {
  return callApi('getMyMember', teamId ? { teamId: teamId } : {})
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

// 应提交口径只在服务端实现（services/expected.py）：
// 看板/报表统一调用 getReportTaskStatus，客户端不再自行按模板范围统计。

// ---------- 填报任务 ----------
async function createReportTask(payload) {
  return callApi('createReportTask', { payload: payload })
}

async function listReportTasks(teamId, status) {
  return callApi('listReportTasks', { teamId: teamId, status: status || '' })
}

async function getReportTask(id) {
  return callApi('getReportTask', { id: id })
}

// 应提交口径唯一入口：单日传 date，区间传 from/to；taskId 可选
async function getReportTaskStatus(params) {
  return callApi('getReportTaskStatus', params || {})
}

async function closeReportTask(id) {
  return callApi('closeReportTask', { id: id })
}

// ---------- 分析引擎（P3）----------
// 指标/规则/结果全部由服务端确定性计算，前端只做展示，不在本地重算。
async function listAnalysisMetrics(teamId) {
  return callApi('listAnalysisMetrics', { teamId: teamId })
}

async function listAnalysisRules(teamId) {
  return callApi('listAnalysisRules', { teamId: teamId })
}

// params: { teamId, from, to }；同一周期重复调用返回既有结果（幂等）
async function runAnalysis(params) {
  return callApi('runAnalysis', params || {})
}

async function retryAnalysisTask(id) {
  return callApi('retryAnalysisTask', { id: id })
}

async function listAnalysisTasks(teamId, limit) {
  return callApi('listAnalysisTasks', { teamId: teamId, limit: limit || 20 })
}

async function getAnalysisTask(id) {
  return callApi('getAnalysisTask', { id: id })
}

async function listAnalysisFindings(taskId) {
  return callApi('listAnalysisFindings', { taskId: taskId })
}

async function getAnalysisOverview(teamId) {
  return callApi('getAnalysisOverview', { teamId: teamId })
}

// ---------- 工作空间与部门（P4）----------
// 一人可属多个空间；切换与列表统一走服务端校验，跨空间访问会被拒绝。
async function listMyWorkspaces() {
  return callApi('listMyWorkspaces')
}

// params: { teamId } 或 { workspaceId }；都不传时返回默认空间
async function switchWorkspace(params) {
  return callApi('switchWorkspace', params || {})
}

// ---------- Web 扫码登录（P5）----------
// 仅在空间所有者的微信里调用；ticket 为 Web 端生成的一次性 32 位 hex
async function confirmWebLogin(ticket) {
  return callApi('confirmWebLogin', { ticket: ticket })
}

async function createWorkspace(name, memberName, teamName) {
  return callApi('createWorkspace', {
    name: name,
    memberName: memberName,
    teamName: teamName || '',
  })
}

async function updateWorkspace(workspaceId, patch) {
  return callApi('updateWorkspace', Object.assign({ workspaceId: workspaceId }, patch || {}))
}

async function listWorkspaceMembers(workspaceId) {
  return callApi('listWorkspaceMembers', { workspaceId: workspaceId })
}

async function updateWorkspaceMember(workspaceId, id, patch) {
  return callApi('updateWorkspaceMember', {
    workspaceId: workspaceId,
    id: id,
    patch: patch || {},
  })
}

async function listDepartments(workspaceId) {
  return callApi('listDepartments', { workspaceId: workspaceId })
}

async function createDepartment(workspaceId, name, parentId, leaderUid) {
  return callApi('createDepartment', {
    workspaceId: workspaceId,
    name: name,
    parentId: parentId || '',
    leaderUid: leaderUid || '',
  })
}

async function updateDepartment(workspaceId, id, patch) {
  return callApi('updateDepartment',
    Object.assign({ workspaceId: workspaceId, id: id }, patch || {}))
}

// ---------- 消息通知（P6）----------
// settings: { daily_remind: true, due_remind: false, ... }，只记录本人在当前空间的授权结果
async function saveNotificationSettings(teamId, settings) {
  return callApi('saveNotificationSettings', {
    teamId: teamId,
    settings: settings || {},
  })
}

async function getNotificationSettings(teamId) {
  return callApi('getNotificationSettings', { teamId: teamId })
}

// 订阅授权所需的模板 ID；唯一来源是服务端 WX_TMPL_*，小程序只做缓存
async function getSubscribeTemplates() {
  return callApi('getSubscribeTemplates', {})
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
  createReportTask,
  listReportTasks,
  getReportTask,
  getReportTaskStatus,
  closeReportTask,
  listAnalysisMetrics,
  listAnalysisRules,
  runAnalysis,
  retryAnalysisTask,
  listAnalysisTasks,
  getAnalysisTask,
  listAnalysisFindings,
  getAnalysisOverview,
  listMyWorkspaces,
  switchWorkspace,
  confirmWebLogin,
  createWorkspace,
  updateWorkspace,
  listWorkspaceMembers,
  updateWorkspaceMember,
  listDepartments,
  createDepartment,
  updateDepartment,
  saveNotificationSettings,
  getNotificationSettings,
  getSubscribeTemplates,
  getMyEntry,
  saveEntry,
  listMyEntries,
  listTeamEntries,
  logAction,
}
