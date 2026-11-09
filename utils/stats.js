// 统计引擎：按模板“聚合配置”对明细做聚合（对应任务书 stats_daily 口径，周期汇总基于同一套逻辑）
// 明细行结构：{ team_id, user_id, entry_date, form_data:[{rowId, values}], status, template_id, template_version }

function toNumber(v) {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return isNaN(n) ? null : n
}

function emptyMetric() {
  return { sum: 0, count: 0, avg: 0 }
}

function addToMetric(metric, value) {
  const n = toNumber(value)
  if (n === null) return
  metric.sum += n
  metric.count += 1
  metric.avg = metric.count > 0 ? metric.sum / metric.count : 0
}

// fields: 模板字段定义数组；返回该模板需要参与统计的字段
function aggregateFields(fields) {
  return (fields || []).filter(function (f) {
    return f.aggregate && f.aggregate.enabled
  })
}

// 对一组明细聚合，返回 { byUser, byField, rowCount, submittedCount, entryCount }
// 口径：仅 status === 'submitted' 的明细计入条数与字段聚合（草稿不计入统计）
function aggregateEntries(entries, fields) {
  const aggFields = aggregateFields(fields)
  const byUser = {}
  const byField = {}
  let rowCount = 0
  let submittedCount = 0

  aggFields.forEach(function (f) {
    byField[f.fieldKey] = { label: f.label, unit: f.unit || '', method: f.aggregate.method || 'sum', metric: emptyMetric() }
  })

  ;(entries || []).forEach(function (entry) {
    const uid = entry.user_id
    if (!byUser[uid]) byUser[uid] = { userId: uid, rowCount: 0, submitted: 0, fields: {} }
    aggFields.forEach(function (f) {
      if (!byUser[uid].fields[f.fieldKey]) byUser[uid].fields[f.fieldKey] = emptyMetric()
    })
    if (entry.status === 'submitted') {
      byUser[uid].submitted = 1
      submittedCount += 1
      const rows = entry.form_data || []
      rowCount += rows.length
      byUser[uid].rowCount += rows.length
      rows.forEach(function (row) {
        const values = row.values || {}
        aggFields.forEach(function (f) {
          const raw = values[f.fieldKey]
          if (f.aggregate.method === 'count') {
            if (raw !== undefined && raw !== null && raw !== '') {
              byUser[uid].fields[f.fieldKey].count += 1
              byField[f.fieldKey].metric.count += 1
            }
            return
          }
          addToMetric(byUser[uid].fields[f.fieldKey], raw)
          addToMetric(byField[f.fieldKey].metric, raw)
        })
      })
    }
  })

  // 计算按成员的 avg（sum/count 已维护）
  const users = Object.keys(byUser).map(function (uid) {
    const u = byUser[uid]
    const fieldList = Object.keys(u.fields).map(function (key) {
      const m = u.fields[key]
      return {
        fieldKey: key,
        label: byField[key] ? byField[key].label : key,
        unit: byField[key] ? byField[key].unit : '',
        method: byField[key] ? byField[key].method : 'sum',
        sum: round2(m.sum),
        count: m.count,
        avg: round2(m.avg),
      }
    })
    return { userId: uid, rowCount: u.rowCount, submitted: u.submitted, fields: fieldList }
  })

  const fieldList = Object.keys(byField).map(function (key) {
    const f = byField[key]
    return {
      fieldKey: key,
      label: f.label,
      unit: f.unit,
      method: f.method,
      sum: round2(f.metric.sum),
      count: f.metric.count,
      avg: round2(f.metric.avg),
    }
  })

  return {
    byUser: byUser,
    users: users,
    fields: fieldList,
    rowCount: rowCount,
    submittedCount: submittedCount,
    entryCount: (entries || []).length,
  }
}

function round2(n) {
  return Math.round(n * 100) / 100
}

// 按成员的展示值（依据聚合方式）
function displayValue(field, method) {
  if (method === 'avg') return field.avg
  if (method === 'count') return field.count
  return field.sum
}

// 跨模板版本合并聚合（FR-S06）
// 结果按 fieldKey 合并（sum/count 相加，avg 由 sum/count 重算），label 取出现该
// fieldKey 的最新模板版本（版本快照语义）。resolver(entry) 返回该 entry 的字段定义。
function aggregateEntriesMulti(entries, resolver) {
  const groups = {} // groupKey -> { fields, entries }
  const groupOrder = []
  const entryGroup = new Map()
  ;(entries || []).forEach(function (entry, idx) {
    const fields = resolver(entry)
    if (!fields) return
    const key = idx // 保证每个 entry 被处理且保留顺序
    groups[key] = { fields: fields, entries: [entry] }
    groupOrder.push(key)
    entryGroup.set(idx, key)
  })

  // 合并 byField 与 byUser：fieldKey -> metric
  const byField = {}
  const fieldMeta = {} // fieldKey -> { label, unit, method }（取最后一个出现的版本定义）
  const byUser = {}
  let rowCount = 0
  let submittedCount = 0

  groupOrder.forEach(function (key) {
    const g = groups[key]
    const r = aggregateEntries(g.entries, g.fields)
    rowCount += r.rowCount
    submittedCount += r.submittedCount
    r.fields.forEach(function (fd) {
      fieldMeta[fd.fieldKey] = { label: fd.label, unit: fd.unit, method: fd.method }
      if (!byField[fd.fieldKey]) {
        byField[fd.fieldKey] = { sum: 0, count: 0 }
      }
      byField[fd.fieldKey].sum += fd.sum
      byField[fd.fieldKey].count += fd.count
    })
    r.users.forEach(function (u) {
      if (!byUser[u.userId]) {
        byUser[u.userId] = { userId: u.userId, rowCount: 0, submitted: 0, fields: {} }
      }
      const target = byUser[u.userId]
      target.rowCount += u.rowCount
      if (u.submitted) target.submitted = 1
      u.fields.forEach(function (fd) {
        if (!target.fields[fd.fieldKey]) target.fields[fd.fieldKey] = { sum: 0, count: 0 }
        target.fields[fd.fieldKey].sum += fd.sum
        target.fields[fd.fieldKey].count += fd.count
      })
    })
  })

  const users = Object.keys(byUser).map(function (uid) {
    const u = byUser[uid]
    const fieldList = Object.keys(u.fields).map(function (key) {
      const meta = fieldMeta[key] || { label: key, unit: '', method: 'sum' }
      const m = u.fields[key]
      return {
        fieldKey: key,
        label: meta.label,
        unit: meta.unit,
        method: meta.method,
        sum: round2(m.sum),
        count: m.count,
        avg: m.count > 0 ? round2(m.sum / m.count) : 0,
      }
    })
    return { userId: uid, rowCount: u.rowCount, submitted: u.submitted, fields: fieldList }
  })

  const fieldList = Object.keys(byField).map(function (key) {
    const meta = fieldMeta[key]
    const m = byField[key]
    return {
      fieldKey: key,
      label: meta.label,
      unit: meta.unit,
      method: meta.method,
      sum: round2(m.sum),
      count: m.count,
      avg: m.count > 0 ? round2(m.sum / m.count) : 0,
    }
  })

  return {
    byUser: byUser,
    users: users,
    fields: fieldList,
    rowCount: rowCount,
    submittedCount: submittedCount,
    entryCount: (entries || []).length,
  }
}

module.exports = { aggregateEntries, aggregateEntriesMulti, aggregateFields, displayValue, round2 }
