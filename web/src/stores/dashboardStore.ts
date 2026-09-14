import { create } from 'zustand'

export interface DashboardEntry {
  session_id: string
  display_name: string
  running: boolean
  task_type: string
  step: string
  course_name: string
  last_event: string
  last_event_time: number
}

interface DashboardState {
  entries: Record<string, DashboardEntry>
  updateFromSocket: (data: Record<string, unknown>) => void
  setEntry: (sessionId: string, entry: Partial<DashboardEntry>) => void
  removeEntry: (sessionId: string) => void
}

export const useDashboardStore = create<DashboardState>((set, get) => ({
  entries: {},

  updateFromSocket: (data) => {
    const sid = data.session_id as string
    const prev = get().entries[sid] || {
      session_id: sid,
      display_name: '',
      running: false,
      task_type: '',
      step: '',
      course_name: '',
      last_event: '',
      last_event_time: 0,
    }
    set({
      entries: {
        ...get().entries,
        [sid]: {
          ...prev,
          running: true,
          task_type: (data.task_type as string) || prev.task_type,
          step: (data.step as string) || (data.event_type as string) || prev.step,
          course_name: (data.course_name as string) || prev.course_name,
          last_event: (data.event_type as string) || '',
          last_event_time: Date.now(),
        },
      },
    })
  },

  setEntry: (sessionId, entry) => {
    const prev = get().entries[sessionId] || {
      session_id: sessionId,
      display_name: '',
      running: false,
      task_type: '',
      step: '',
      course_name: '',
      last_event: '',
      last_event_time: 0,
    }
    set({ entries: { ...get().entries, [sessionId]: { ...prev, ...entry } } })
  },

  removeEntry: (sessionId) => {
    const next = { ...get().entries }
    delete next[sessionId]
    set({ entries: next })
  },
}))
