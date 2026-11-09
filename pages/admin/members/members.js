const session = require('../../../utils/session')
const store = require('../../../utils/store')

Page({
  data: {
    loading: true,
    denied: false,
    errorText: '',
    members: [],
    inviteCode: '',
    isOwner: false,
    roleLabels: { member: '成员', manager: '管理员', owner: '负责人' },
  },

  onShow: async function () {
    this.setData({ loading: true, errorText: '' })
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
      this.setData({
        inviteCode: ctx.team.team_id,
        isOwner: ctx.member.role === 'owner',
      })
      await this.loadMembers()
    } catch (e) {
      this.setData({ loading: false, errorText: e.message || '加载失败' })
    }
  },

  loadMembers: async function () {
    try {
      const ctx = this.ctx
      const members = await store.listMembers(ctx.team.team_id)
      this.setData({
        loading: false,
        members: members.map(function (m) {
          return {
            id: m.id,
            userId: m.user_id,
            name: m.name,
            role: m.role,
            status: m.status,
            active: m.status === 'active',
            joinedAt: String(m.joined_at || '').slice(0, 10),
          }
        }),
      })
    } catch (e) {
      this.setData({ loading: false, errorText: e.message || '加载失败' })
    }
  },

  copyInvite: function () {
    wx.setClipboardData({
      data: this.data.inviteCode,
      success: function () {
        wx.showToast({ title: '邀请码已复制', icon: 'success' })
      },
    })
  },

  changeRole: function (e) {
    const id = e.currentTarget.dataset.id
    const name = e.currentTarget.dataset.name
    const self = this
    const roles = ['member', 'manager']
    wx.showActionSheet({
      itemList: ['设为普通成员', '设为管理员'],
      success: async function (res) {
        const role = roles[res.tapIndex]
        try {
          await store.updateMember(id, { role: role })
          await store.logAction(self.ctx.team.team_id, 'member_role_change', 'members', String(id), {
            name: name,
            role: role,
          })
          wx.showToast({ title: '已更新', icon: 'success' })
          self.loadMembers()
        } catch (err) {
          wx.showToast({ title: err.message || '操作失败', icon: 'none' })
        }
      },
    })
  },

  toggleStatus: function (e) {
    const id = e.currentTarget.dataset.id
    const active = e.currentTarget.dataset.active === '1'
    const self = this
    wx.showModal({
      title: active ? '停用成员' : '启用成员',
      content: active ? '停用后该成员无法登录查看与提交数据。确认停用？' : '将恢复该成员的访问权限。确认启用？',
      success: async function (res) {
        if (!res.confirm) return
        try {
          await store.updateMember(id, { status: active ? 'disabled' : 'active' })
          await store.logAction(self.ctx.team.team_id, active ? 'member_disable' : 'member_enable', 'members', String(id), {})
          wx.showToast({ title: '已更新', icon: 'success' })
          self.loadMembers()
        } catch (err) {
          wx.showToast({ title: err.message || '操作失败', icon: 'none' })
        }
      },
    })
  },

  removeOne: function (e) {
    const id = e.currentTarget.dataset.id
    const name = e.currentTarget.dataset.name
    const self = this
    wx.showModal({
      title: '移除成员',
      content: '将 ' + name + ' 移出团队，历史记录保留。确认移除？',
      success: async function (res) {
        if (!res.confirm) return
        try {
          await store.removeMember(id)
          await store.logAction(self.ctx.team.team_id, 'member_remove', 'members', String(id), { name: name })
          wx.showToast({ title: '已移除', icon: 'success' })
          self.loadMembers()
        } catch (err) {
          wx.showToast({ title: err.message || '操作失败', icon: 'none' })
        }
      },
    })
  },
})
