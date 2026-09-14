import { create } from 'zustand'
import { api } from '@/lib/api'
import type { AccountInfo, SavedSession, ActiveSession } from '@/types/api'

interface LoginSuccess {
  session_id: string
  account: AccountInfo
}

interface AuthState {
  activeSessions: Record<string, ActiveSession>
  savedSessions: SavedSession[]
  loading: boolean
  error: string | null

  loginPassword: (phone: string, password: string) => Promise<string>
  resumeSession: (index: number) => Promise<string>
  relogin: (index: number) => Promise<string>
  logout: (sessionId: string) => void
  loadSavedSessions: () => Promise<void>
  loadActiveSessions: () => Promise<void>
}

export const useAuthStore = create<AuthState>((set, get) => ({
  activeSessions: {},
  savedSessions: [],
  loading: false,
  error: null,

  loginPassword: async (phone, password) => {
    const data = await api.post<LoginSuccess>('/auth/login/passwd', { phone, password })
    set({
      activeSessions: {
        ...get().activeSessions,
        [data.session_id]: {
          session_id: data.session_id,
          display_name: data.account.name,
          login_method: 'password',
          task_running: false,
          task_type: '',
          task_step: '',
          task_course_name: '',
        },
      },
    })
    return data.session_id
  },

  resumeSession: async (index) => {
    const data = await api.post<LoginSuccess>('/auth/login/session', { index })
    set({
      activeSessions: {
        ...get().activeSessions,
        [data.session_id]: {
          session_id: data.session_id,
          display_name: data.account.name,
          login_method: 'session',
          task_running: false,
          task_type: '',
          task_step: '',
          task_course_name: '',
        },
      },
    })
    return data.session_id
  },

  relogin: async (index) => {
    const data = await api.post<LoginSuccess>('/auth/login/relogin', { index })
    set({
      activeSessions: {
        ...get().activeSessions,
        [data.session_id]: {
          session_id: data.session_id,
          display_name: data.account.name,
          login_method: 'relogin',
          task_running: false,
          task_type: '',
          task_step: '',
          task_course_name: '',
        },
      },
    })
    return data.session_id
  },

  logout: (sessionId) => {
    api.delete(`/auth/logout/${sessionId}`).catch(() => {})
    const next = { ...get().activeSessions }
    delete next[sessionId]
    set({ activeSessions: next })
  },

  loadSavedSessions: async () => {
    const data = await api.get<SavedSession[]>('/sessions')
    set({ savedSessions: data })
  },

  loadActiveSessions: async () => {
    try {
      const data = await api.get<ActiveSession[]>('/sessions/active')
      const obj: Record<string, ActiveSession> = {}
      for (const s of data) obj[s.session_id] = s
      set({ activeSessions: obj })
    } catch {
      // server may not be running yet
    }
  },
}))
