// 模板字段校验（前端一次校验，与提交数据共用）
// 字段元数据：{ fieldKey, label, type, required, default, unit, placeholder, options, validation:{min,max,pattern}, aggregate, sort }
const NUMERIC_TYPES = ['integer', 'decimal', 'money']

function isNumeric(type) {
  return NUMERIC_TYPES.indexOf(type) >= 0
}

function toNumber(v) {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return isNaN(n) ? NaN : n
}

// 校验单行 values，返回错误对象 { fieldKey: message }，无错误返回 null
function validateRow(values, fields) {
  const errors = {}
  for (let i = 0; i < fields.length; i++) {
    const f = fields[i]
    const v = values[f.fieldKey]
    const empty = v === undefined || v === null || v === '' || (Array.isArray(v) && v.length === 0)
    if (f.required && empty) {
      errors[f.fieldKey] = f.label + '为必填项'
      continue
    }
    if (empty) continue
    if (isNumeric(f.type)) {
      const n = toNumber(v)
      if (isNaN(n)) {
        errors[f.fieldKey] = f.label + '必须是数字'
        continue
      }
      const min = f.validation && f.validation.min
      const max = f.validation && f.validation.max
      if (min !== undefined && min !== null && min !== '' && n < Number(min)) {
        errors[f.fieldKey] = f.label + '不能小于 ' + min
        continue
      }
      if (max !== undefined && max !== null && max !== '' && n > Number(max)) {
        errors[f.fieldKey] = f.label + '不能大于 ' + max
        continue
      }
      if (f.type === 'integer' && Math.floor(n) !== n) {
        errors[f.fieldKey] = f.label + '必须是整数'
        continue
      }
    }
    if (f.type === 'select' && f.options && f.options.length > 0 && f.options.indexOf(v) < 0) {
      errors[f.fieldKey] = f.label + '的选项不合法'
      continue
    }
    if (f.type === 'multiselect' && f.options && f.options.length > 0) {
      const arr = Array.isArray(v) ? v : [v]
      for (let j = 0; j < arr.length; j++) {
        if (f.options.indexOf(arr[j]) < 0) {
          errors[f.fieldKey] = f.label + '的选项不合法'
          break
        }
      }
      continue
    }
    const pattern = f.validation && f.validation.pattern
    if (pattern) {
      try {
        const re = new RegExp(pattern)
        if (!re.test(String(v))) {
          errors[f.fieldKey] = f.label + '格式不正确'
        }
      } catch (e) {
        // 模板里的正则不合法时忽略该规则
      }
    }
  }
  const keys = Object.keys(errors)
  return keys.length > 0 ? errors : null
}

module.exports = { validateRow, isNumeric, toNumber }
