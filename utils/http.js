// 自有服务端接入层：替代旧云开发调用层
// 保持 callApi(action, payload) -> data | throw 的契约，store.js 业务函数零改动
const config = require('./config')

const TOKEN_KEY = 'auth_token'

let unauthorizedHook = null
let memoryToken = '' // 存储不可用时的本次会话兜底

function getToken() {
  try {
    return wx.getStorageSync(TOKEN_KEY) || memoryToken
  } catch (e) {
    return memoryToken
  }
}

function setToken(token) {
  memoryToken = token
  try {
    wx.setStorageSync(TOKEN_KEY, token)
  } catch (e) {
    // 存储失败不阻断本次会话
  }
}

function clearToken() {
  memoryToken = ''
  try {
    wx.removeStorageSync(TOKEN_KEY)
  } catch (e) {
    // 忽略存储错误
  }
}

// 由 session 层注册：401 时清理登录态并引导重新登录
function onUnauthorized(fn) {
  unauthorizedHook = fn
}

function request(path, data, withAuth) {
  return new Promise(function (resolve, reject) {
    if (config.IS_PLACEHOLDER) {
      reject(new Error('服务端地址尚未配置，请修改 utils/config.js 的 RELEASE_BASE / DEV_BASE'))
      return
    }
    const header = { 'content-type': 'application/json' }
    if (withAuth) {
      const token = getToken()
      if (!token) {
        reject(new Error('登录已过期，请重新登录'))
        return
      }
      header.Authorization = 'Bearer ' + token
    }
    wx.request({
      url: config.BASE_URL + path,
      method: 'POST',
      data: data || {},
      header: header,
      timeout: config.REQUEST_TIMEOUT,
      success: function (res) {
        const r = res && res.data
        if (res.statusCode === 401) {
          clearToken()
          if (unauthorizedHook) unauthorizedHook()
          reject(new Error((r && r.message) || '登录已过期，请重新登录'))
          return
        }
        if (res.statusCode < 200 || res.statusCode >= 300 || !r) {
          reject(new Error((r && r.message) || '网络异常，请重试'))
          return
        }
        if (r.ok === false) {
          reject(new Error(r.message || '请求失败，请重试'))
          return
        }
        resolve(r.data)
      },
      fail: function () {
        reject(new Error('网络连接失败，请检查网络后重试'))
      },
    })
  })
}

// 业务 API：与旧云函数 api 的 { ok, data | message } 契约一致
async function callApi(action, payload) {
  return request('/api', Object.assign({ action: action }, payload || {}), true)
}

// 微信登录：wx.login 的 code -> 自有服务端 code2session -> JWT
async function callLogin(code) {
  return request('/auth/login', { code: code }, false)
}

module.exports = { callApi, callLogin, getToken, setToken, clearToken, onUnauthorized }
