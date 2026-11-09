// 动态模板表单渲染器：按模板 fields 渲染控件，支持单条 / 可重复多行
// rows 结构：[{ rowId, values: { fieldKey: value } }]
let rowSeq = 0

function genRowId() {
  rowSeq += 1
  return 'r' + Date.now() + '_' + rowSeq
}

function sortedFields(fields) {
  return (fields || []).slice().sort(function (a, b) {
    return (a.sort || 0) - (b.sort || 0)
  })
}

// 多选字段的选中状态映射：checks[fieldKey][option] = true/false
function buildChecks(fields, values) {
  const checks = {}
  fields.forEach(function (f) {
    if (f.type !== 'multiselect' || !f.options) return
    const state = {}
    const selected = values[f.fieldKey] || []
    f.options.forEach(function (opt) {
      state[opt] = selected.indexOf(opt) >= 0
    })
    checks[f.fieldKey] = state
  })
  return checks
}

Component({
  properties: {
    // 模板对象 { entry_mode, fields }
    template: {
      type: Object,
      value: null,
      observer: function () {
        this.rebuild()
      },
    },
    // 外部传入的行数据（编辑已有记录时）
    value: {
      type: Array,
      value: null,
      observer: function () {
        this.rebuild()
      },
    },
    disabled: {
      type: Boolean,
      value: false,
    },
  },

  data: {
    fields: [],
    entryMode: 'single',
    rows: [],
    repeatable: false,
  },

  lifetimes: {
    attached: function () {
      this.rebuild()
    },
  },

  methods: {
    rebuild: function () {
      const tpl = this.properties.template
      if (!tpl || !tpl.fields) return
      const fields = sortedFields(tpl.fields)
      const repeatable = tpl.entry_mode === 'repeatable'
      let rows = []
      const incoming = this.properties.value
      if (incoming && incoming.length > 0) {
        rows = incoming.map(function (r) {
          return { rowId: r.rowId || genRowId(), values: Object.assign({}, r.values || {}) }
        })
      } else {
        // 默认值 + 一行空行
        const values = {}
        fields.forEach(function (f) {
          if (f.default !== undefined && f.default !== null && f.default !== '') {
            values[f.fieldKey] = f.default
          }
        })
        rows = [{ rowId: genRowId(), values: values }]
      }
      rows = rows.map(function (r) {
        r.checks = buildChecks(fields, r.values)
        return r
      })
      this.setData({
        fields: fields,
        entryMode: tpl.entry_mode || 'single',
        repeatable: repeatable,
        rows: rows,
      })
      this.emit()
    },

    emit: function () {
      this.triggerEvent('change', {
        rows: this.data.rows.map(function (r) {
          return { rowId: r.rowId, values: Object.assign({}, r.values) }
        }),
      })
    },

    setValue: function (rowId, key, val) {
      const rows = this.data.rows
      for (let i = 0; i < rows.length; i++) {
        if (rows[i].rowId === rowId) {
          const patch = {}
          patch['rows[' + i + '].values.' + key] = val
          this.setData(patch)
          break
        }
      }
      this.emit()
    },

    onInput: function (e) {
      const rowId = e.currentTarget.dataset.row
      const key = e.currentTarget.dataset.key
      this.setValue(rowId, key, e.detail.value)
    },

    onSelect: function (e) {
      const rowId = e.currentTarget.dataset.row
      const key = e.currentTarget.dataset.key
      const idx = Number(e.detail.value)
      const fieldKey = e.currentTarget.dataset.fieldindex
      const f = this.data.fields[Number(fieldKey)]
      if (!f || !f.options) return
      this.setValue(rowId, key, f.options[idx])
    },

    onDate: function (e) {
      const rowId = e.currentTarget.dataset.row
      const key = e.currentTarget.dataset.key
      this.setValue(rowId, key, e.detail.value)
    },

    onCheck: function (e) {
      const rowId = e.currentTarget.dataset.row
      const key = e.currentTarget.dataset.key
      const rows = this.data.rows
      for (let i = 0; i < rows.length; i++) {
        if (rows[i].rowId === rowId) {
          const merged = Object.assign({}, rows[i].values)
          merged[key] = e.detail.value
          const patch = {}
          patch['rows[' + i + '].values.' + key] = e.detail.value
          patch['rows[' + i + '].checks.' + key] = buildChecks(this.data.fields, merged)[key]
          this.setData(patch)
          break
        }
      }
      this.emit()
    },

    addRow: function () {
      const values = {}
      this.data.fields.forEach(function (f) {
        if (f.default !== undefined && f.default !== null && f.default !== '') {
          values[f.fieldKey] = f.default
        }
      })
      const rows = this.data.rows.concat([
        { rowId: genRowId(), values: values, checks: buildChecks(this.data.fields, values) },
      ])
      this.setData({ rows: rows })
      this.emit()
    },

    removeRow: function (e) {
      const rowId = e.currentTarget.dataset.row
      const rows = this.data.rows.filter(function (r) {
        return r.rowId !== rowId
      })
      if (rows.length === 0) {
        const values = {}
        this.data.fields.forEach(function (f) {
          if (f.default !== undefined && f.default !== null && f.default !== '') {
            values[f.fieldKey] = f.default
          }
        })
        rows.push({ rowId: genRowId(), values: values, checks: buildChecks(this.data.fields, values) })
      }
      this.setData({ rows: rows })
      this.emit()
    },

    // 供父页面读取当前数据
    getRows: function () {
      return this.data.rows.map(function (r) {
        return { rowId: r.rowId, values: Object.assign({}, r.values) }
      })
    },
  },
})
