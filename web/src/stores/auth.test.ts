import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from './auth'

const TOKEN_KEY = 'jinribao_web_token'

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
})

describe('auth store', () => {
  it('初始化时读取 localStorage 中的 token', () => {
    localStorage.setItem(TOKEN_KEY, 't1')

    const store = useAuthStore()

    expect(store.token).toBe('t1')
    expect(store.loggedIn).toBe(true)
  })

  it('setToken 更新登录态', () => {
    const store = useAuthStore()

    store.setToken('t2')

    expect(store.token).toBe('t2')
    expect(store.loggedIn).toBe(true)
  })

  it('logout 清空内存与本地缓存', () => {
    localStorage.setItem(TOKEN_KEY, 't1')
    localStorage.setItem('jinribao_web_workspace', 'W1')
    localStorage.setItem('jinribao_web_team', 'T1')
    const store = useAuthStore()
    store.setToken('t1')

    store.logout()

    expect(store.token).toBe('')
    expect(store.loggedIn).toBe(false)
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
    expect(localStorage.getItem('jinribao_web_workspace')).toBeNull()
    expect(localStorage.getItem('jinribao_web_team')).toBeNull()
  })
})
