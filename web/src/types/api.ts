export interface AccountInfo {
  puid: number
  name: string
  sex: string
  phone: string
  school: string
  stu_id: string
}

export interface LoginSuccess {
  session_id: string
  account: AccountInfo
}

export interface Course {
  index: number
  course_id: string
  class_id: string
  name: string
  teacher_name: string
  state: string
  state_value: number
}

export interface Chapter {
  index: number
  chapter_id: string
  label: string
  name: string
  layer: number
  point_total: number
  point_finished: number
  is_finished: boolean
}

export interface Exam {
  index: number
  exam_id: string
  name: string
  status: string
  expire_time: string
}

export interface TaskStatus {
  running: boolean
  type: string
  course_name: string
  step: string
}

export interface TaskOverride {
  video_enable?: boolean
  video_speed?: number
  video_report_rate?: number
  video_wait?: number
  work_enable?: boolean
  work_export?: boolean
  work_fallback_fuzzer?: boolean
  work_fallback_save?: boolean
  work_wait?: number
  document_enable?: boolean
  document_wait?: number
  exam_fallback_fuzzer?: boolean
  exam_confirm_submit?: boolean
  exam_persubmit_delay?: number
}

export interface SavedSession {
  index: number
  phone: string
  phone_raw: string
  puid: number
  name: string
  name_raw: string
  has_passwd: boolean
}

export interface ActiveSession {
  session_id: string
  display_name: string
  login_method: string
  task_running: boolean
  task_type: string
  task_step: string
  task_course_name: string
}

export interface SearcherTemplate {
  label: string
  icon: string
  color: string
  desc: string
  fields: SearcherField[]
}

export interface SearcherField {
  key: string
  label: string
  type: string
  default: unknown
  placeholder?: string
  required?: boolean
  options?: string[]
  rows?: number
  help?: string
}

export interface LogFile {
  name: string
  size: number
  modified: number
}

export interface EventLogEntry {
  timestamp: number
  type: string
  message: string
  data?: Record<string, unknown>
}
