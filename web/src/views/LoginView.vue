<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createTicket, pollTicket, setToken } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useWorkspaceStore } from '../stores/workspace'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const ws = useWorkspaceStore()

const qrcode = ref('')
const statusText = ref('')
const error = ref('')
const loading = ref(false)
const failed = ref(false)

let ticket = ''
let pollTimer: number | undefined
let refreshTimer: number | undefined
let deadline = 0

function stopPolling() {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
}

function stopRefresh() {
  if (refreshTimer) {
    window.clearTimeout(refreshTimer)
    refreshTimer = undefined
  }
}

async function start() {
  stopPolling()
  stopRefresh()
  loading.value = true
  error.value = ''
  failed.value = false
  qrcode.value = ''
  statusText.value = '正在生成登录二维码…'
  try {
    const data = await createTicket()
    ticket = data.ticket
    qrcode.value = data.qrcode
    statusText.value = '请使用微信扫码，并在小程序内确认登录'
    deadline = Date.now() + data.expiresIn * 1000
    pollTimer = window.setInterval(poll, 1500)
  } catch (e: any) {
    error.value = e?.message || '二维码生成失败，请稍后重试'
    statusText.value = ''
    failed.value = true
  } finally {
    loading.value = false
  }
}

async function poll() {
  if (!ticket) return
  try {
    const data = await pollTicket(ticket)
    if (data.status === 'confirmed' && data.token) {
      stopPolling()
      setToken(data.token)
      auth.setToken(data.token)
      try {
        await ws.loadSpaces()
      } catch {
        // 工作空间列表加载失败不阻断登录，布局层会再次尝试
      }
      ElMessage.success('登录成功')
      const redirect = (route.query.redirect as string) || '/dashboard'
      router.replace(redirect)
      return
    }
    if (data.status === 'expired' || data.status === 'consumed') {
      expire()
    }
  } catch (e: any) {
    if (e?.status === 401) return
    stopPolling()
    error.value = e?.message || '登录状态查询失败'
  }
  if (Date.now() > deadline) expire()
}

function expire() {
  stopPolling()
  ticket = ''
  statusText.value = '二维码已过期，正在重新生成…'
  // 过期自动换新码，用户无需手动操作
  refreshTimer = window.setTimeout(start, 800)
}

onMounted(start)
onBeforeUnmount(() => {
  stopPolling()
  stopRefresh()
})
</script>

<template>
  <div class="login-page">
    <div class="card">
      <div class="brand">报数机器人AI</div>
      <div class="subtitle">管理后台 · 微信扫码登录</div>

      <div class="qrcode-box">
        <img v-if="qrcode" :src="qrcode" alt="登录二维码" class="qrcode" />
        <div v-else class="placeholder">
          <span>{{ loading ? '生成中…' : '二维码不可用' }}</span>
        </div>
      </div>

      <p v-if="statusText" class="status">{{ statusText }}</p>
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />

      <el-button class="refresh" :loading="loading" @click="start">刷新二维码</el-button>

      <div class="tip">
        空间 owner/admin 或团队 owner/manager 可登录。扫码后请在小程序内点击「确认登录」。
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #eef3ff 0%, #f7f9fc 100%);
}

.card {
  width: 380px;
  padding: 36px 32px 28px;
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 12px 40px rgba(31, 45, 61, 0.12);
  text-align: center;
}

.brand {
  font-size: 22px;
  font-weight: 600;
}

.subtitle {
  margin-top: 8px;
  font-size: 13px;
  color: #8a94a6;
}

.qrcode-box {
  margin: 24px auto 12px;
  width: 220px;
  height: 220px;
  border: 1px solid #e6eaf0;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.qrcode {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.placeholder {
  display: flex;
  flex-direction: column;
  gap: 8px;
  color: #8a94a6;
  font-size: 13px;
}

.status {
  margin: 8px 0 12px;
  font-size: 13px;
  color: #5e6d82;
}

.refresh {
  margin-top: 12px;
  width: 100%;
}

.tip {
  margin-top: 18px;
  font-size: 12px;
  line-height: 1.6;
  color: #8a94a6;
}
</style>
