import { create } from 'zustand'
import { api } from '@/lib/api'
import type { TaskStatus, TaskOverride, Course, Chapter, Exam, EventLogEntry } from '@/types/api'

interface PerSessionTask {
  status: TaskStatus
  courses: Course[]
  chapters: Chapter[]
  exams: Exam[]
  eventLog: EventLogEntry[]
  currentChapter: number  // 当前处理的章节索引
  currentTaskPoint: number  // 当前处理的任务点索引
  currentActivity: {
    type: 'question' | 'video' | 'document' | 'exam' | 'wait' | 'none'
    data: Record<string, unknown> | null
  }
}

interface TaskState {
  tasks: Record<string, PerSessionTask>

  initSession: (sessionId: string) => void
  loadCourses: (sessionId: string) => Promise<void>
  loadChapters: (sessionId: string, courseIndex: number) => Promise<{ name: string; chapters: Chapter[] }>
  loadExams: (sessionId: string, courseIndex: number) => Promise<Exam[]>
  loadStatus: (sessionId: string) => Promise<void>
  startTask: (sessionId: string, courseIndices: number[], overrides?: TaskOverride) => Promise<void>
  startExam: (sessionId: string, examIndex: number, courseIndex: number, exportOnly: boolean, overrides?: TaskOverride) => Promise<void>
  cancelTask: (sessionId: string) => Promise<void>
  addEvent: (sessionId: string, entry: EventLogEntry) => void
  updateFromSocket: (sessionId: string, event: string, data: Record<string, unknown>) => void
  clearEvents: (sessionId: string) => void
  removeSession: (sessionId: string) => void
}

function makeDefault(): PerSessionTask {
  return {
    status: { running: false, type: '', course_name: '', step: 'idle' },
    courses: [],
    chapters: [],
    exams: [],
    eventLog: [],
    currentChapter: -1,
    currentTaskPoint: -1,
    currentActivity: { type: 'none', data: null },
  }
}

function ensure(sessionId: string, tasks: Record<string, PerSessionTask>): Record<string, PerSessionTask> {
  if (tasks[sessionId]) return tasks
  return { ...tasks, [sessionId]: makeDefault() }
}

export const useTaskStore = create<TaskState>((set, get) => ({
  tasks: {},

  initSession: (sessionId) => {
    if (!get().tasks[sessionId]) {
      set({ tasks: { ...get().tasks, [sessionId]: makeDefault() } })
    }
  },

  loadCourses: async (sessionId) => {
    const courses = await api.get<Course[]>(`/sessions/${sessionId}/courses`)
    const tasks = ensure(sessionId, get().tasks)
    tasks[sessionId] = { ...tasks[sessionId], courses }
    set({ tasks: { ...tasks } })
  },

  loadChapters: async (sessionId, courseIndex) => {
    const data = await api.get<{ course_name: string; chapters: Chapter[] }>(
      `/sessions/${sessionId}/courses/${courseIndex}/chapters`
    )
    const tasks = ensure(sessionId, get().tasks)
    tasks[sessionId] = { ...tasks[sessionId], chapters: data.chapters }
    set({ tasks: { ...tasks } })
    return data
  },

  loadExams: async (sessionId, courseIndex) => {
    const exams = await api.get<Exam[]>(`/sessions/${sessionId}/courses/${courseIndex}/exams`)
    const tasks = ensure(sessionId, get().tasks)
    tasks[sessionId] = { ...tasks[sessionId], exams }
    set({ tasks: { ...tasks } })
    return exams
  },

  loadStatus: async (sessionId) => {
    const data = await api.get<TaskStatus>(`/sessions/${sessionId}/tasks/status`)
    const tasks = ensure(sessionId, get().tasks)
    tasks[sessionId] = { ...tasks[sessionId], status: data }
    set({ tasks: { ...tasks } })
  },

  startTask: async (sessionId, courseIndices, overrides) => {
    await api.post(`/sessions/${sessionId}/tasks/start`, {
      course_indices: courseIndices, overrides,
    })
  },

  startExam: async (sessionId, examIndex, courseIndex, exportOnly, overrides) => {
    await api.post(`/sessions/${sessionId}/tasks/start-exam`, {
      exam_index: examIndex, course_index: courseIndex, export_only: exportOnly, overrides,
    })
  },

  cancelTask: async (sessionId) => {
    await api.post(`/sessions/${sessionId}/tasks/cancel`)
  },

  addEvent: (sessionId, entry) => {
    const tasks = ensure(sessionId, get().tasks)
    const prev = tasks[sessionId]
    const log = [...prev.eventLog, entry].slice(-500)
    tasks[sessionId] = { ...prev, eventLog: log }
    set({ tasks: { ...tasks } })
  },

  updateFromSocket: (sessionId, event, data) => {
    const tasks = ensure(sessionId, get().tasks)
    const prev = tasks[sessionId]
    const updated = { ...prev }

    // Determine whether to add to event log (throttle spam events)
    let addToLog = true
    let logMessage = ''
    let logData = data

    switch (event) {
      case 'task:progress':
        // 更新章节进度 (初次加载或刷新)
        if ((data.event === 'chapters_loaded' || data.event === 'chapters_updated') && data.chapters) {
          const newChapters = data.chapters as Chapter[]
          if (updated.chapters.length === 0 || data.event === 'chapters_loaded') {
            updated.chapters = newChapters
          } else {
            // 合并更新已有的章节进度
            updated.chapters = updated.chapters.map(ch => {
              const found = newChapters.find((n: Chapter) => n.index === ch.index)
              return found ? { ...ch, point_finished: found.point_finished, point_total: found.point_total, is_finished: found.is_finished } : ch
            })
          }
        }
        // 追踪当前处理的章节和任务点
        if (data.chapter_index !== undefined) {
          updated.currentChapter = data.chapter_index as number
        }
        if (data.task_point_index !== undefined) {
          updated.currentTaskPoint = data.task_point_index as number
        }
        updated.status = {
          ...updated.status,
          course_name: (data.course_name as string) || updated.status.course_name,
          step: (data.event as string) || updated.status.step,
        }
        break
      case 'task:question':
        updated.currentActivity = { type: 'question', data }
        break
      case 'task:video':
        updated.currentActivity = { type: 'video', data }
        addToLog = false  // 每秒更新，不记日志
        break
      case 'task:video_report':
        addToLog = true
        break
      case 'task:exam_meta':
        updated.currentActivity = { type: 'exam', data }
        break
      case 'task:wait':
        updated.currentActivity = { type: 'wait', data }
        break
      case 'task:captcha':
        if (data.status === 'recognizing') {
          addToLog = false  // 识别中不记日志
        } else {
          logMessage = `验证码${data.status === 'success' ? '通过' : '失败'}`
        }
        break
      case 'task:face':
        if (data.status === 'preparing') {
          addToLog = false
        }
        break
      case 'task:complete':
        if (data.status === 'all_done') {
          updated.status = { ...updated.status, running: false, step: 'done' }
          updated.currentActivity = { type: 'none', data: null }
        }
        break
      case 'task:error':
        updated.currentActivity = { type: 'none', data: null }
        break
    }

    if (addToLog) {
      const msg = logMessage || (typeof data.event === 'string' ? String(data.event) : event)
      updated.eventLog = [...prev.eventLog, { timestamp: Date.now(), type: event, message: msg, data: logData }].slice(-500)
    }

    tasks[sessionId] = updated
    set({ tasks: { ...tasks } })
  },

  clearEvents: (sessionId) => {
    const tasks = { ...get().tasks }
    if (tasks[sessionId]) {
      tasks[sessionId] = { ...tasks[sessionId], eventLog: [] }
      set({ tasks })
    }
  },

  removeSession: (sessionId) => {
    const tasks = { ...get().tasks }
    delete tasks[sessionId]
    set({ tasks })
  },
}))
