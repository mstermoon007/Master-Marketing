// 日期工具：本地时区，格式 YYYY-MM-DD
// 补录窗口：与服务端 server/app/handlers/entries.py 的 BACKFILL_DAYS 保持一致
const BACKFILL_DAYS = 31

function pad(n) {
  return n < 10 ? '0' + n : '' + n
}

function fmtDate(d) {
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
}

function today() {
  return fmtDate(new Date())
}

function parseDate(s) {
  const parts = String(s).split('-')
  return new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]))
}

function addDays(s, n) {
  const d = parseDate(s)
  d.setDate(d.getDate() + n)
  return fmtDate(d)
}

// 所在周的周一
function weekStart(s) {
  const d = parseDate(s)
  const day = d.getDay()
  const diff = day === 0 ? -6 : 1 - day
  d.setDate(d.getDate() + diff)
  return fmtDate(d)
}

function monthStart(s) {
  const d = parseDate(s)
  return fmtDate(new Date(d.getFullYear(), d.getMonth(), 1))
}

function monthEnd(s) {
  const d = parseDate(s)
  return fmtDate(new Date(d.getFullYear(), d.getMonth() + 1, 0))
}

function yearStart(s) {
  const d = parseDate(s)
  return d.getFullYear() + '-01-01'
}

function yearEnd(s) {
  const d = parseDate(s)
  return d.getFullYear() + '-12-31'
}

// 根据周期类型返回 [start, end]
function rangeOf(period, dateStr) {
  if (period === 'week') {
    const start = weekStart(dateStr)
    return [start, addDays(start, 6)]
  }
  if (period === 'month') {
    return [monthStart(dateStr), monthEnd(dateStr)]
  }
  if (period === 'year') {
    return [yearStart(dateStr), yearEnd(dateStr)]
  }
  return [dateStr, dateStr]
}

function periodLabel(period, dateStr) {
  const d = parseDate(dateStr)
  if (period === 'week') {
    const start = weekStart(dateStr)
    return start + ' ~ ' + addDays(start, 6)
  }
  if (period === 'month') {
    return d.getFullYear() + ' 年 ' + (d.getMonth() + 1) + ' 月'
  }
  if (period === 'year') {
    return d.getFullYear() + ' 年'
  }
  return dateStr
}

// 允许补录的最早日期（含当天）
function minEntryDate(todayStr) {
  return addDays(todayStr || today(), -BACKFILL_DAYS)
}

// 日期是否落在可补录窗口内；服务端会再独立校验一次
function isEntryDateAllowed(dateStr, todayStr) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(dateStr))) return false
  const t = todayStr || today()
  return dateStr >= minEntryDate(t) && dateStr <= t
}

function weekName(dateStr) {
  const names = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
  return names[parseDate(dateStr).getDay()]
}

module.exports = {
  today, fmtDate, parseDate, addDays, rangeOf, periodLabel,
  weekStart, monthStart, monthEnd, yearStart, yearEnd,
  BACKFILL_DAYS, minEntryDate, isEntryDateAllowed, weekName,
}
