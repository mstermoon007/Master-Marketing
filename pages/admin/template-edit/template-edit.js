const session = require('../../../utils/session')
const store = require('../../../utils/store')
const dateUtil = require('../../../utils/date')

const TYPE_OPTIONS = [
  { value: 'text', label: '文本' },
  { value: 'textarea', label: '多行文本' },
  { value: 'integer', label: '整数' },
  { value: 'decimal', label: '小数' },
  { value: 'money', label: '金额' },
  { value: 'select', label: '单选' },
  { value: 'multiselect', label: '多选' },
  { value: 'date', label: '日期' },
]
const TYPE_LABELS = TYPE_OPTIONS.map(function (o) {
  return o.label
})

const METHOD_OPTIONS = [
  { value: 'sum', label: '求和' },
  { value: 'avg', label: '平均' },
  { value: 'count', label: '计数' },
]
const METHOD_LABELS = METHOD_OPTIONS.map(function (o) {
  return o.label
})

const SCOPE_OPTIONS = [
  { value: 'all', label: '全员' },
  { value: 'members', label: '指定成员' },
  { value: 'roles', label: '指定角色' },
]
const SCOPE_LABELS = SCOPE_OPTIONS.map(function (o) {
  return o.label
})

function typeLabel(v) {
  for (let i = 0; i < TYPE_OPTIONS.length; i++) {
    if (TYPE_OPTIONS[i].value === v) return TYPE_OPTIONS[i].label
  }
  return v
}

function methodLabel(v) {
  for (let i = 0; i < METHOD_OPTIONS.length; i++) {
    if (METHOD_OPTIONS[i].value === v) return METHOD_OPTIONS[i].label
  }
  return v
}

function genFieldKey() {
  return 'f_' + Math.random().toString(36).slice(2, 8)
}

// 「地产日报」预设字段（线上媒体含抖音/视频号/微信朋友券/其他媒体分渠道）
function estatePresetFields() {
  const mk = function (fieldKey, label, type, sort, extra) {
    return Object.assign(
      {
        fieldKey: fieldKey,
        label: label,
        type: type,
        required: false,
        default: null,
        unit: type === 'textarea' ? '' : '组',
        placeholder: '',
        options: [],
        optionsText: '',
        validation: { min: '', max: '', pattern: '' },
        aggregate: { enabled: type !== 'textarea', method: 'sum', dimension: 'member' },
        sort: sort,
      },
      extra || {}
    )
  }
  return [
    mk('system_input', '系统录入数量', 'integer', 1),
    mk('online_media', '线上媒体获客', 'integer', 2),
    mk('douyin', '抖音', 'integer', 3),
    mk('video_channel', '视频号', 'integer', 4),
    mk('wechat_coupon', '微信朋友券', 'integer', 5),
    mk('other_media', '其他媒体', 'integer', 6),
    mk('offline_self', '线下自拓', 'integer', 7),
    mk('reception_visit', '接待自上', 'integer', 8),
    mk('invite_visit', '邀约到访', 'integer', 9),
    mk('wechat_friends', '微信好友数量', 'integer', 10, { unit: '个' }),
    mk('customer_profile', '客户描摹', 'textarea', 11, { required: true, placeholder: '记录重点客户情况、意向与跟进动作' }),
  ]
}

function emptyField(sort) {
  return {
    fieldKey: genFieldKey(),
    label: '',
    type: 'text',
    required: false,
    default: null,
    unit: '',
    placeholder: '',
    options: [],
    optionsText: '',
    validation: { min: '', max: '', pattern: '' },
    aggregate: { enabled: false, method: 'sum', dimension: 'member' },
    sort: sort,
  }
}

function decorateField(f) {
  const out = Object.assign({}, f)
  out.typeLabel = typeLabel(f.type)
  out.methodLabel = methodLabel(f.aggregate && f.aggregate.method)
  out.optionsText = (f.options || []).join('，')
  out.validation = f.validation || {}
  out.aggregate = f.aggregate || { enabled: false, method: 'sum', dimension: 'member' }
  return out
}

Page({
  data: {
    loading: true,
    denied: false,
    errorText: '',
    editId: null,
    isNew: true,
    name: '',
    description: '',
    entryMode: 'single',
    entryModeLabel: '单条',
    effectiveFrom: '',
    today: '',
    fields: [],
    expandedIndex: -1,
    typeOptions: TYPE_LABELS,
    methodOptions: METHOD_LABELS,
    scopeOptions: SCOPE_LABELS,
    scopeType: 'all',
    scopeTypeLabel: '全员',
    scopeRoleChecks: {},
    memberOptions: [],
    memberChecks: {},
    saving: false,
  },

  scopeTypeValue: 'all',
  scopeRoles: [],
  scopeMemberIds: [],

  onLoad: function (options) {
    if (options && options.id) {
      this.setData({ editId: options.id, isNew: false })
    }
    if (options && options.from) {
      // 基于已发布版本派生新草稿版本
      this.fromId = options.from
      this.setData({ isNew: false, fromVersion: true })
    }
    if (options && options.preset === 'estate') {
      this.presetEstate = true
    }
  },

  onShow: async function () {
    this.setData({ loading: true, today: dateUtil.today() })
    try {
      const ctx = await session.loadContext()
      if (!ctx.member || !ctx.team) {
        wx.switchTab({ url: '/pages/index/index' })
        return
      }
      if (!session.isManager(ctx.member)) {
        this.setData({ loading: false, denied: true })
        return
      }
      this.ctx = ctx
      await this.loadPage(ctx)
    } catch (e) {
      this.setData({ loading: false, errorText: e.message || '加载失败' })
    }
  },

  loadPage: async function (ctx) {
    const members = await store.listMembers(ctx.team.team_id)
    const memberOptions = members
      .filter(function (m) {
        return m.status === 'active'
      })
      .map(function (m) {
        return { userId: m.user_id, name: m.name }
      })
    if (this.data.editId) {
      const row = await store.getTemplate(this.data.editId)
      if (!row) {
        this.setData({ loading: false, errorText: '模板不存在' })
        return
      }
      if (row.status !== 'draft') {
        this.setData({ loading: false, errorText: '只有草稿可以编辑，已发布版本请新建版本' })
        return
      }
      this.applyTemplateRow(row, memberOptions)
    } else if (this.fromId) {
      // 新版本：复制已发布版本的定义，沿用 template_id，版本号 = max+1
      const row = await store.getTemplate(this.fromId)
      if (!row) {
        this.setData({ loading: false, errorText: '来源模板不存在' })
        return
      }
      const version = await store.nextVersion(ctx.team.team_id, row.template_id)
      row.version = version
      row.status = 'draft'
      row.effective_from = ''
      this.newVersionBase = { templateId: row.template_id, version: version, name: row.name }
      this.applyTemplateRow(row, memberOptions)
    } else if (this.presetEstate) {
      const fields = estatePresetFields().map(decorateField)
      this.setData({
        loading: false,
        isNew: true,
        name: '地产日报模板',
        description: '系统录入 / 线上媒体获客 / 线下自拓 / 接待自上 / 邀约到访 / 微信好友 / 客户描摹',
        entryMode: 'single',
        entryModeLabel: '单条',
        effectiveFrom: '',
        fields: fields,
        expandedIndex: -1,
        scopeType: 'all',
        scopeTypeLabel: '全员',
        scopeRoleChecks: {},
        memberOptions: memberOptions,
        memberChecks: {},
      })
    } else {
      this.scopeTypeValue = 'all'
      this.scopeRoles = []
      this.scopeMemberIds = []
      this.setData({
        loading: false,
        isNew: true,
        name: '',
        description: '',
        entryMode: 'single',
        entryModeLabel: '单条',
        effectiveFrom: '',
        fields: [decorateField(emptyField(1))],
        expandedIndex: 0,
        scopeType: 'all',
        scopeTypeLabel: '全员',
        scopeRoleChecks: {},
        memberOptions: memberOptions,
        memberChecks: {},
      })
    }
  },

  applyTemplateRow: function (row, memberOptions) {
    const scope = row.scope || { type: 'all' }
    const fields = (row.fields || []).map(decorateField)
    const scopeRoleChecks = {}
    const memberChecks = {}
    ;(scope.roles || []).forEach(function (r) {
      scopeRoleChecks[r] = true
    })
    ;(scope.memberIds || []).forEach(function (id) {
      memberChecks[id] = true
    })
    this.scopeTypeValue = scope.type || 'all'
    this.scopeRoles = scope.roles || []
    this.scopeMemberIds = scope.memberIds || []
    this.setData({
      loading: false,
      name: row.name,
      description: row.description || '',
      entryMode: row.entry_mode,
      entryModeLabel: row.entry_mode === 'repeatable' ? '可重复多行' : '单条',
      effectiveFrom: row.effective_from || '',
      fields: fields,
      scopeType: scope.type || 'all',
      scopeTypeLabel: scopeLabel(scope.type || 'all'),
      scopeRoleChecks: scopeRoleChecks,
      memberOptions: memberOptions,
      memberChecks: memberChecks,
    })
  },

  // ---------- 基础信息 ----------
  onName: function (e) {
    this.setData({ name: e.detail.value })
  },

  onDescription: function (e) {
    this.setData({ description: e.detail.value })
  },

  onEntryMode: function (e) {
    const val = Number(e.detail.value) === 1 ? 'repeatable' : 'single'
    this.setData({
      entryMode: val,
      entryModeLabel: val === 'repeatable' ? '可重复多行' : '单条',
    })
  },

  onEffectiveFrom: function (e) {
    this.setData({ effectiveFrom: e.detail.value })
  },

  onScopeType: function (e) {
    const opt = SCOPE_OPTIONS[Number(e.detail.value)]
    this.scopeTypeValue = opt.value
    this.setData({ scopeType: opt.value, scopeTypeLabel: opt.label })
  },

  onRoleCheck: function (e) {
    this.scopeRoles = e.detail.value
    const checks = {}
    this.scopeRoles.forEach(function (r) {
      checks[r] = true
    })
    this.setData({ scopeRoleChecks: checks })
  },

  onMemberToggle: function (e) {
    const idx = e.currentTarget.dataset.idx
    const opt = this.data.memberOptions[Number(idx)]
    if (!opt) return
    const id = opt.userId
    const checks = Object.assign({}, this.data.memberChecks)
    if (checks[id]) {
      delete checks[id]
      this.scopeMemberIds = this.scopeMemberIds.filter(function (x) {
        return x !== id
      })
    } else {
      checks[id] = true
      this.scopeMemberIds = this.scopeMemberIds.concat([id])
    }
    this.setData({ memberChecks: checks })
  },

  // ---------- 字段编辑 ----------
  toggleField: function (e) {
    const idx = Number(e.currentTarget.dataset.idx)
    this.setData({ expandedIndex: this.data.expandedIndex === idx ? -1 : idx })
  },

  addField: function () {
    const fields = this.data.fields.concat([decorateField(emptyField(this.data.fields.length + 1))])
    this.setData({ fields: fields, expandedIndex: fields.length - 1 })
  },

  removeField: function (e) {
    const idx = Number(e.currentTarget.dataset.idx)
    const fields = this.data.fields
      .filter(function (f, i) {
        return i !== idx
      })
      .map(function (f, i) {
        return Object.assign({}, f, { sort: i + 1 })
      })
    this.setData({ fields: fields, expandedIndex: -1 })
  },

  moveField: function (e) {
    const idx = Number(e.currentTarget.dataset.idx)
    const dir = e.currentTarget.dataset.dir
    const fields = this.data.fields.slice()
    const target = dir === 'up' ? idx - 1 : idx + 1
    if (target < 0 || target >= fields.length) return
    const tmp = fields[idx]
    fields[idx] = fields[target]
    fields[target] = tmp
    this.setData({
      fields: fields.map(function (f, i) {
        return Object.assign({}, f, { sort: i + 1 })
      }),
    })
  },

  patchField: function (idx, patch) {
    const patchData = {}
    Object.keys(patch).forEach(function (k) {
      patchData['fields[' + idx + '].' + k] = patch[k]
    })
    this.setData(patchData)
  },

  onFieldLabel: function (e) {
    this.patchField(Number(e.currentTarget.dataset.idx), { label: e.detail.value })
  },

  onFieldKey: function (e) {
    this.patchField(Number(e.currentTarget.dataset.idx), { fieldKey: e.detail.value.trim() })
  },

  onFieldType: function (e) {
    const idx = Number(e.currentTarget.dataset.idx)
    const opt = TYPE_OPTIONS[Number(e.detail.value)]
    this.patchField(idx, { type: opt.value, typeLabel: opt.label })
  },

  onFieldRequired: function (e) {
    this.patchField(Number(e.currentTarget.dataset.idx), { required: e.detail.value })
  },

  onFieldUnit: function (e) {
    this.patchField(Number(e.currentTarget.dataset.idx), { unit: e.detail.value })
  },

  onFieldPlaceholder: function (e) {
    this.patchField(Number(e.currentTarget.dataset.idx), { placeholder: e.detail.value })
  },

  onFieldOptions: function (e) {
    const idx = Number(e.currentTarget.dataset.idx)
    const text = e.detail.value
    const opts = text
      .split(/[,，]/)
      .map(function (s) {
        return s.trim()
      })
      .filter(function (s) {
        return !!s
      })
    this.patchField(idx, { optionsText: text, options: opts })
  },

  onFieldMin: function (e) {
    this.patchField(Number(e.currentTarget.dataset.idx), { 'validation.min': e.detail.value })
  },

  onFieldMax: function (e) {
    this.patchField(Number(e.currentTarget.dataset.idx), { 'validation.max': e.detail.value })
  },

  onFieldAgg: function (e) {
    const idx = Number(e.currentTarget.dataset.idx)
    const agg = Object.assign({}, this.data.fields[idx].aggregate, { enabled: e.detail.value })
    this.patchField(idx, { aggregate: agg })
  },

  onFieldMethod: function (e) {
    const idx = Number(e.currentTarget.dataset.idx)
    const opt = METHOD_OPTIONS[Number(e.detail.value)]
    const agg = Object.assign({}, this.data.fields[idx].aggregate, { method: opt.value })
    this.patchField(idx, { aggregate: agg, methodLabel: opt.label })
  },

  // ---------- 保存 ----------
  onSave: async function () {
    await this.persistDraft(false)
  },

  onSaveAndPublish: async function () {
    const self = this
    wx.showModal({
      title: '保存并发布',
      content: '发布后立即对范围内成员生效，成员端下一次打开即按新模板填写；已提交的历史数据不受影响。确认发布？',
      success: async function (res) {
        if (res.confirm) await self.persistDraft(true)
      },
    })
  },

  persistDraft: async function (publishNow) {
    const name = this.data.name.trim()
    if (!name) {
      wx.showToast({ title: '请填写模板名称', icon: 'none' })
      return
    }
    const rawFields = this.data.fields.map(function (f, i) {
      return {
        fieldKey: (f.fieldKey || '').trim() || genFieldKey(),
        label: (f.label || '').trim(),
        type: f.type,
        required: !!f.required,
        default: null,
        unit: (f.unit || '').trim(),
        placeholder: (f.placeholder || '').trim(),
        options: f.type === 'select' || f.type === 'multiselect' ? f.options : [],
        validation: {
          min: f.validation && f.validation.min !== '' ? Number(f.validation.min) : null,
          max: f.validation && f.validation.max !== '' ? Number(f.validation.max) : null,
        },
        aggregate: {
          enabled: !!(f.aggregate && f.aggregate.enabled),
          method: (f.aggregate && f.aggregate.method) || 'sum',
          dimension: 'member',
        },
        sort: i + 1,
      }
    })
    // 基础校验
    const seen = {}
    const KEY_RE = /^[A-Za-z_][A-Za-z0-9_]*$/
    for (let i = 0; i < rawFields.length; i++) {
      const f = rawFields[i]
      if (!f.label) {
        wx.showToast({ title: '第' + (i + 1) + '个字段缺少标签', icon: 'none' })
        return
      }
      if (!KEY_RE.test(f.fieldKey)) {
        wx.showToast({ title: '字段「' + f.label + '」标识需为字母/数字/下划线', icon: 'none' })
        return
      }
      if (seen[f.fieldKey]) {
        wx.showToast({ title: '字段标识 ' + f.fieldKey + ' 重复', icon: 'none' })
        return
      }
      seen[f.fieldKey] = true
      if ((f.type === 'select' || f.type === 'multiselect') && (!f.options || f.options.length === 0)) {
        wx.showToast({ title: '字段「' + f.label + '」缺少选项', icon: 'none' })
        return
      }
    }
    const scope = { type: this.scopeTypeValue, memberIds: this.scopeMemberIds, roles: this.scopeRoles }
    const payload = {
      name: name,
      description: this.data.description.trim(),
      entry_mode: this.data.entryMode,
      fields: rawFields,
      scope: scope,
      effective_from: this.data.effectiveFrom || dateUtil.today(),
    }
    this.setData({ saving: true })
    try {
      let savedId = null
      if (this.fromId && this.newVersionBase) {
        // 新版本草稿：沿用 template_id，版本号已在 loadPage 算好
        payload.team_id = this.ctx.team.team_id
        payload.template_id = this.newVersionBase.templateId
        payload.version = this.newVersionBase.version
        payload.status = 'draft'
        const saved = await store.createDraft(payload)
        savedId = saved.id
        store.logAction(this.ctx.team.team_id, 'template_new_version', 'form_templates', this.newVersionBase.templateId, {
          version: this.newVersionBase.version,
          name: name,
        })
      } else if (this.data.isNew) {
        const templateId = 'tpl_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6)
        payload.team_id = this.ctx.team.team_id
        payload.template_id = templateId
        payload.version = 1
        payload.status = 'draft'
        const saved = await store.createDraft(payload)
        savedId = saved.id
        store.logAction(this.ctx.team.team_id, 'template_create', 'form_templates', templateId, { name: name })
      } else {
        await store.updateTemplateRow(this.data.editId, payload)
        savedId = this.data.editId
      }
      if (publishNow) {
        // 用发布接口返回的版本号/生效日（编辑已有草稿时 payload 里没有 version）
        const published = await store.publishTemplate(savedId)
        const ver = published && published.version ? published.version : (payload.version || '')
        const effective = published && published.effective_from ? published.effective_from : '今天'
        wx.showToast({ title: '已发布 v' + ver + '，' + effective + ' 起生效', icon: 'none' })
      } else {
        wx.showToast({ title: '草稿已保存', icon: 'success' })
      }
      setTimeout(function () {
        wx.navigateBack()
      }, publishNow ? 1100 : 700)
    } catch (e) {
      wx.showToast({ title: e.message || '保存失败', icon: 'none' })
    }
    this.setData({ saving: false })
  },
})

function scopeLabel(v) {
  for (let i = 0; i < SCOPE_OPTIONS.length; i++) {
    if (SCOPE_OPTIONS[i].value === v) return SCOPE_OPTIONS[i].label
  }
  return '全员'
}
