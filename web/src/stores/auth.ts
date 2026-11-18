import { defineStore } from 'pinia'
import { getToken } from '../api/client'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: getToken(),
  }),
  getters: {
    loggedIn: (state) => Boolean(state.token),
  },
  actions: {
    setToken(token: string) {
      this.token = token
    },
    logout() {
      this.token = ''
      localStorage.removeItem('jinribao_web_token')
      localStorage.removeItem('jinribao_web_workspace')
      localStorage.removeItem('jinribao_web_team')
    },
  },
})
