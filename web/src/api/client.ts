import type { WorkspaceBrief } from './types'

const BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')
const TOKEN_KEY = 'jinribao_web_token'

export class ApiError extends Error {
  status: number

  constructor(message: string, status = 0) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: 'Bearer ' + token } : {}
}

function handleUnauthorized(): void {
  clearToken()
  if (window.location.pathname !== '/login') {
    window.location.assign('/login')
  }
}

async function readJson(resp: Response): Promise<any> {
  try {
    return await resp.json()
  } catch {
    throw new ApiError('服务返回格式异常，请稍后重试', resp.status)
  }
}

/** 统一业务入口：POST /api { action, ...payload } */
export async function callApi<T = any>(action: string, payload: Record<string, unknown> = {}): Promise<T> {
  const resp = await fetch(BASE + '/api', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ action, ...payload }),
  })
  if (resp.status === 401) {
    handleUnauthorized()
    throw new ApiError('登录已过期，请重新扫码', 401)
  }
  const json = await readJson(resp)
  if (!json.ok) {
    throw new ApiError(json.message || '请求失败', resp.status)
  }
  return json.data as T
}

export interface TicketResponse {
  ticket: string
  qrcode: string
  expiresIn: number
}

export interface TicketStatusResponse {
  status: 'pending' | 'confirmed' | 'consumed' | 'expired'
  token?: string
  expiresIn?: number
  workspaces?: WorkspaceBrief[]
}

export async function createTicket(): Promise<TicketResponse> {
  const resp = await fetch(BASE + '/auth/web/ticket', { method: 'POST' })
  const json = await readJson(resp)
  if (!json.ok) throw new ApiError(json.message || '二维码生成失败', resp.status)
  return json.data as TicketResponse
}

export async function pollTicket(ticket: string): Promise<TicketStatusResponse> {
  const resp = await fetch(BASE + '/auth/web/ticket/status', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ticket }),
  })
  const json = await readJson(resp)
  if (!json.ok) throw new ApiError(json.message || '登录状态查询失败', resp.status)
  return json.data as TicketStatusResponse
}

export async function refreshToken(): Promise<{ token: string; expiresIn: number }> {
  const resp = await fetch(BASE + '/auth/web/refresh', {
    method: 'POST',
    headers: authHeaders(),
  })
  const json = await readJson(resp)
  if (!json.ok) throw new ApiError(json.message || '登录已过期', resp.status)
  return json.data
}

/**
 * 导出 Excel：成功返回二进制流，失败时解析后端 message。
 */
export async function downloadExport(payload: Record<string, unknown>): Promise<Blob> {
  const resp = await fetch(BASE + '/api/export/entries', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(payload),
  })
  if (resp.status === 401) {
    handleUnauthorized()
    throw new ApiError('登录已过期，请重新扫码', 401)
  }
  const contentType = resp.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    const json = await readJson(resp)
    throw new ApiError(json.message || '导出失败', resp.status)
  }
  if (!resp.ok) throw new ApiError('导出失败，请稍后重试', resp.status)
  return resp.blob()
}

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}
