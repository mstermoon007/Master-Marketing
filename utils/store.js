// 数据访问层：teams / members / form_templates / daily_entries / audit_logs
const { cloud } = require('./cloud')

const db = cloud.database

function unwrap(res) {
  if (res.error) {
    const err = new Error(res.error.message || '请求失败')
    err.code = res.error.code
    throw err
  }
  return res.data
}

// ---------- 团队 ----------
function genTeamId() {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
  let s = ''
  for (let i = 0; i < 6; i++) {
    s += chars.charAt(Math.floor(Math.random() * chars.length))
  }
  return 'T' + s
}

async function createTeam(name, uid, memberName) {
  const teamId = genTeamId()
  const team = unwrap(
    await db
      .from('teams')
      .insert({ team_id: teamId, name: name, owner_uid: uid, config: { memberSeeTeamTotal: false } })
      .select()
  )[0]
  const member = unwrap(
    await db
      .from('members')
      .insert({ team_id: teamId, user_id: uid, name: memberName, role: 'owner', status: 'active' })
      .select()
  )[0]
  return { team: team, member: member }
}

async function findTeamByCode(code) {
  const rows = unwrap(await db.from('teams').select('*').eq('team_id', code).limit(1))
  return rows && rows.length ? rows[0] : null
}

async function joinTeam(teamId, uid, memberName) {
  const exists = unwrap(
    await db.from('members').select('*').eq('team_id', teamId).eq('user_id', uid).limit(1)
  )
  if (exists && exists.length) {
    // 新策略下成员可见自己的行（含停用状态）：停用成员需明确提示
    if (exists[0].status !== 'active') {
      throw new Error('你已在团队名单中但处于停用状态，请联系管理员启用')
    }
    return exists[0]
  }
  try {
    const rows = unwrap(
      await db
        .from('members')
        .insert({ team_id: teamId, user_id: uid, name: memberName, role: 'member', status: 'active' })
        .select()
    )
    return rows[0]
  } catch (e) {
    // 唯一约束冲突兜底：并发加入或 RLS 可见性边缘情况
    if (e.code === '23505' || /duplicate|unique/i.test(e.message || '')) {
      throw new Error('你已在团队名单中，请退出重进或联系管理员')
    }
    throw e
  }
}

async function getTeam(teamId) {
  const rows = unwrap(await db.from('teams').select('*').eq('team_id', teamId).limit(1))
  return rows && rows.length ? rows[0] : null
}

async function updateTeamConfig(teamId, config) {
  return unwrap(await db.from('teams').update({ config: config }).eq('team_id', teamId).select())
}

// ---------- 成员 ----------
async function getMyMember(uid) {
  const rows = unwrap(await db.from('members').select('*').eq('user_id', uid).eq('status', 'active').limit(1))
  return rows && rows.length ? rows[0] : null
}

async function listMembers(teamId) {
  return unwrap(await db.from('members').select('*').eq('team_id', teamId).order('joined_at', { ascending: true }))
}

async function updateMember(id, patch) {
  return unwrap(await db.from('members').update(patch).eq('id', id).select())
}

async function removeMember(id) {
  return unwrap(await db.from('members').delete().eq('id', id).select())
}

// ---------- 模板 ----------
async function listTemplates(teamId) {
  return unwrap(
    await db
      .from('form_templates')
      .select('*')
      .eq('team_id', teamId)
      .order('template_id', { ascending: true })
      .order('version', { ascending: false })
  )
}

async function getTemplate(id) {
  const rows = unwrap(await db.from('form_templates').select('*').eq('id', id).limit(1))
  return rows && rows.length ? rows[0] : null
}

async function listPublishedTemplates(teamId) {
  return unwrap(
    await db
      .from('form_templates')
      .select('*')
      .eq('team_id', teamId)
      .eq('status', 'published')
      .order('version', { ascending: false })
  )
}

async function createDraft(payload) {
  return unwrap(await db.from('form_templates').insert(payload).select())[0]
}

async function updateTemplateRow(id, patch) {
  return unwrap(await db.from('form_templates').update(patch).eq('id', id).select())[0]
}

async function deleteTemplateRow(id) {
  return unwrap(await db.from('form_templates').delete().eq('id', id).select())
}

// 发布模板（管理端"随时调整"的统一入口）：
// 草稿 → published（立即生效）→ 归档同模板旧版本 → 冻结快照写审计
async function publishTemplate(teamId, id, userId) {
  const row = await getTemplate(id)
  if (!row) throw new Error('模板不存在')
  if (row.status !== 'draft') throw new Error('只有草稿可以发布')
  const dateUtil = require('./date')
  // 先置 published（避免"无生效版本"窗口期），再归档旧版本
  await updateTemplateRow(id, {
    status: 'published',
    effective_from: row.effective_from || dateUtil.today(),
    published_by: userId,
    published_at: new Date().toISOString(),
  })
  const all = await listTemplates(teamId)
  for (let i = 0; i < all.length; i++) {
    const t = all[i]
    if (t.template_id === row.template_id && t.status === 'published' && String(t.id) !== String(id)) {
      await updateTemplateRow(t.id, { status: 'archived' })
    }
  }
  await logAction(teamId, 'template_publish', 'form_templates', row.template_id, {
    version: row.version,
    fields: row.fields,
    scope: row.scope,
    effectiveFrom: row.effective_from || dateUtil.today(),
  })
  return row
}

// 模板版本号：同 template_id 的最大版本 + 1
async function nextVersion(teamId, templateId) {
  const rows = unwrap(
    await db
      .from('form_templates')
      .select('version')
      .eq('team_id', teamId)
      .eq('template_id', templateId)
      .order('version', { ascending: false })
      .limit(1)
  )
  return rows && rows.length ? Number(rows[0].version) + 1 : 1
}

// 当前生效模板：published、生效时间已到、命中下发范围，取版本最高
// ignoreScope=true 时跳过范围判定（供管理端看板/报表按成员逐个判定范围使用）
async function getActiveTemplate(teamId, member, ignoreScope) {
  const list = await listPublishedTemplates(teamId)
  const today = require('./date').today()
  const candidates = list.filter(function (t) {
    if (!t.effective_from || t.effective_from <= today) return true
    return false
  })
  candidates.sort(function (a, b) {
    if (a.effective_from === b.effective_from) return Number(b.version) - Number(a.version)
    return (b.effective_from || '') > (a.effective_from || '') ? 1 : -1
  })
  for (let i = 0; i < candidates.length; i++) {
    if (ignoreScope || inScope(candidates[i].scope, member)) return candidates[i]
  }
  return null
}

function inScope(scope, member) {
  if (!scope || !scope.type || scope.type === 'all') return true
  if (scope.type === 'members') {
    return (scope.memberIds || []).indexOf(member.user_id) >= 0
  }
  if (scope.type === 'roles') {
    return (scope.roles || []).indexOf(member.role) >= 0
  }
  return true
}

// ---------- 录入 ----------
async function getMyEntry(teamId, userId, date) {
  const rows = unwrap(
    await db
      .from('daily_entries')
      .select('*')
      .eq('team_id', teamId)
      .eq('user_id', userId)
      .eq('entry_date', date)
      .limit(1)
  )
  return rows && rows.length ? rows[0] : null
}

async function saveEntry(payload) {
  // 幂等键：team_id + user_id + entry_date（唯一约束）
  const rows = unwrap(
    await db
      .from('daily_entries')
      .upsert(payload, { onConflict: 'team_id,user_id,entry_date' })
      .select()
  )
  return rows[0]
}

async function listMyEntries(teamId, userId, limit) {
  return unwrap(
    await db
      .from('daily_entries')
      .select('*')
      .eq('team_id', teamId)
      .eq('user_id', userId)
      .order('entry_date', { ascending: false })
      .limit(limit || 60)
  )
}

async function listTeamEntries(teamId, from, to) {
  return unwrap(
    await db
      .from('daily_entries')
      .select('*')
      .eq('team_id', teamId)
      .gte('entry_date', from)
      .lte('entry_date', to)
      .order('entry_date', { ascending: false })
  )
}

async function listEntriesByUser(teamId, userId, from, to) {
  return unwrap(
    await db
      .from('daily_entries')
      .select('*')
      .eq('team_id', teamId)
      .eq('user_id', userId)
      .gte('entry_date', from)
      .lte('entry_date', to)
      .order('entry_date', { ascending: false })
  )
}

// ---------- 审计 ----------
async function logAction(teamId, action, targetType, targetId, detail) {
  try {
    await db.from('audit_logs').insert({
      team_id: teamId,
      action: action,
      target_type: targetType || null,
      target_id: targetId ? String(targetId) : null,
      detail: detail || null,
    })
  } catch (e) {
    // 审计失败不阻断主流程
  }
}

module.exports = {
  unwrap,
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
  inScope,
  getMyEntry,
  saveEntry,
  listMyEntries,
  listTeamEntries,
  listEntriesByUser,
  logAction,
}
