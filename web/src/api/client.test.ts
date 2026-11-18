import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  callApi,
  clearToken,
  createTicket,
  downloadExport,
  getToken,
  pollTicket,
  refreshToken,
  setToken,
} from './client'

interface MockInit {
  status?: number
  contentType?: string
  rawBody?: string
  blob?: Blob
}

function mockResponse(body: unknown, init: MockInit = {}): Response {
  const status = init.status ?? 200
  return {
    status,
    ok: status < 400,
    headers: {
      get: (name: string) =>
        name.toLowerCase() === 'content-type'
          ? (init.contentType ?? 'application/json')
          : null,
    },
    json: async () => {
      if (init.rawBody !== undefined) return JSON.parse(init.rawBody)
      return body
    },
    blob: async () => init.blob ?? new Blob(['xlsx']),
  } as unknown as Response
}

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  localStorage.clear()
  window.history.replaceState({}, '', '/login')
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('token 存取', () => {
  it('set/get/clearToken', () => {
    expect(getToken()).toBe('')
    setToken('t1')
    expect(getToken()).toBe('t1')
    clearToken()
    expect(getToken()).toBe('')
  })
})

describe('callApi', () => {
  it('发送 action + payload，并带上 Bearer 头', async () => {
    setToken('t1')
    fetchMock.mockResolvedValue(mockResponse({ ok: true, data: { n: 1 } }))

    const data = await callApi('listTemplates', { teamId: 'T1' })

    expect(data).toEqual({ n: 1 })
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api')
    expect(options.method).toBe('POST')
    expect(options.headers.Authorization).toBe('Bearer t1')
    expect(JSON.parse(options.body)).toEqual({ action: 'listTemplates', teamId: 'T1' })
  })

  it('未登录时不发 Authorization 头', async () => {
    fetchMock.mockResolvedValue(mockResponse({ ok: true, data: [] }))

    await callApi('listTemplates')

    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBeUndefined()
  })

  it('业务失败抛出后端 message 与 HTTP 状态', async () => {
    fetchMock.mockResolvedValue(mockResponse({ ok: false, message: '无权访问' }, { status: 403 }))

    await expect(callApi('listTemplates')).rejects.toMatchObject({
      name: 'ApiError',
      message: '无权访问',
      status: 403,
    })
  })

  it('业务失败但无 message 时使用默认文案', async () => {
    fetchMock.mockResolvedValue(mockResponse({ ok: false }))

    await expect(callApi('listTemplates')).rejects.toThrow('请求失败')
  })

  it('401 清空 token 并抛出登录过期', async () => {
    setToken('t1')
    fetchMock.mockResolvedValue(mockResponse({}, { status: 401 }))

    const error = await callApi('listTemplates').catch((e) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(401)
    expect(error.message).toBe('登录已过期，请重新扫码')
    expect(getToken()).toBe('')
  })

  it('响应不是 JSON 时给出格式异常提示', async () => {
    fetchMock.mockResolvedValue(mockResponse(null, { rawBody: '<html>' }))

    await expect(callApi('listTemplates')).rejects.toThrow('服务返回格式异常，请稍后重试')
  })
})

describe('扫码登录接口', () => {
  it('createTicket 返回票据', async () => {
    const ticket = { ticket: 'abc', qrcode: 'data:image/png;base64,x', expiresIn: 300 }
    fetchMock.mockResolvedValue(mockResponse({ ok: true, data: ticket }))

    await expect(createTicket()).resolves.toEqual(ticket)
    expect(fetchMock.mock.calls[0][0]).toBe('/auth/web/ticket')
  })

  it('createTicket 失败时抛出后端文案', async () => {
    fetchMock.mockResolvedValue(mockResponse({ ok: false, message: '生成失败' }))

    await expect(createTicket()).rejects.toThrow('生成失败')
  })

  it('pollTicket 提交 ticket 并返回状态', async () => {
    fetchMock.mockResolvedValue(mockResponse({ ok: true, data: { status: 'pending' } }))

    await expect(pollTicket('abc')).resolves.toEqual({ status: 'pending' })
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ ticket: 'abc' })
  })

  it('refreshToken 带 Bearer 头', async () => {
    setToken('t1')
    fetchMock.mockResolvedValue(
      mockResponse({ ok: true, data: { token: 't2', expiresIn: 43200 } }),
    )

    await expect(refreshToken()).resolves.toEqual({ token: 't2', expiresIn: 43200 })
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe('Bearer t1')
  })
})

describe('downloadExport', () => {
  it('二进制成功时返回 Blob', async () => {
    const blob = new Blob(['xlsx'])
    fetchMock.mockResolvedValue(mockResponse(null, { contentType: 'application/vnd.ms-excel', blob }))

    await expect(downloadExport({ teamId: 'T1' })).resolves.toBe(blob)
  })

  it('JSON 响应视为业务失败并抛出后端文案', async () => {
    fetchMock.mockResolvedValue(
      mockResponse({ ok: false, message: '导出范围过大' }, { status: 400 }),
    )

    await expect(downloadExport({})).rejects.toThrow('导出范围过大')
  })

  it('非 2xx 且非 JSON 时提示稍后重试', async () => {
    fetchMock.mockResolvedValue(
      mockResponse(null, { status: 500, contentType: 'text/plain' }),
    )

    await expect(downloadExport({})).rejects.toThrow('导出失败，请稍后重试')
  })

  it('401 清空 token', async () => {
    setToken('t1')
    fetchMock.mockResolvedValue(mockResponse({}, { status: 401 }))

    await expect(downloadExport({})).rejects.toThrow('登录已过期，请重新扫码')
    expect(getToken()).toBe('')
  })
})
