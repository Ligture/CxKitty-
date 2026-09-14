import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import { useTaskStore } from '@/stores/taskStore'
import { useSessionSocket } from '@/hooks/useSocket'
import { getSocket } from '@/lib/socket'
import { Card } from '@/components/shared/Card'
import type { TaskOverride, Course, Chapter, Exam } from '@/types/api'
import {
  ChevronRight, Play, Square, LogIn, QrCode, X,
} from 'lucide-react'

export function SessionPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const navigate = useNavigate()
  const isNew = sessionId === 'new'

  const { activeSessions, loginPassword, loadSavedSessions, savedSessions, resumeSession } = useAuthStore()
  const { initSession, loadCourses, loadChapters, loadExams, loadStatus, startTask, cancelTask, tasks } = useTaskStore()

  useSessionSocket(sessionId !== 'new' ? sessionId : undefined)

  const [step, setStep] = useState(sessionId && sessionId !== 'new' ? 2 : 1)
  const [loginPhone, setLoginPhone] = useState('')
  const [loginPasswd, setLoginPasswd] = useState('')
  const [loginError, setLoginError] = useState('')
  const [activeSid, setActiveSid] = useState(sessionId !== 'new' ? sessionId : '')
  const [selectedCourses, setSelectedCourses] = useState<Set<number>>(new Set())
  const [overrides, setOverrides] = useState<TaskOverride>({})
  const [selectedExam, setSelectedExam] = useState<{ examIdx: number; courseIdx: number } | null>(null)

  const session = activeSid ? activeSessions[activeSid] : undefined
  const task = activeSid ? tasks[activeSid] : undefined
  const courses = task?.courses || []
  const chapters = task?.chapters || []
  const eventLog = task?.eventLog || []
  const currentActivity = task?.currentActivity || { type: 'none', data: null }
  const currentChapter = task?.currentChapter ?? -1
  const currentTaskPoint = task?.currentTaskPoint ?? -1
  const status = task?.status || { running: false, type: '', course_name: '', step: 'idle' }

  useEffect(() => {
    if (!isNew && sessionId) {
      setActiveSid(sessionId)
      initSession(sessionId)
      loadCourses(sessionId)
      loadStatus(sessionId)    // 检查是否有运行中任务 → 自动切到步骤4
      loadSavedSessions()
    } else if (isNew) {
      loadSavedSessions()
    }
  }, [sessionId])

  useEffect(() => {
    if (status.running && status.step !== 'done') setStep(4)
    else if (status.step === 'done') setStep(5)
  }, [status.running, status.step])

  const handleLogin = async () => {
    setLoginError('')
    try {
      const sid = await loginPassword(loginPhone, loginPasswd)
      setActiveSid(sid)
      initSession(sid)
      await loadCourses(sid)
      // Pre-select active courses
      const t = useTaskStore.getState().tasks[sid]
      const activeIndices = (t?.courses || [])
        .map((c: Course, i: number) => c.state_value === 0 ? i : -1)
        .filter((i: number) => i >= 0)
      setSelectedCourses(new Set(activeIndices))
      setStep(2)
    } catch (e) {
      setLoginError(e instanceof Error ? e.message : '登录失败')
    }
  }

  const handleStartTask = async () => {
    if (!activeSid || selectedCourses.size === 0) return
    try {
      await startTask(activeSid, [...selectedCourses], overrides)
      setStep(4)
    } catch (e) {
      alert(e instanceof Error ? e.message : '启动任务失败')
    }
  }

  const handleCancel = async () => {
    if (!activeSid) return
    await cancelTask(activeSid)
  }

  // Step 1: Login
  if (step === 1 && (!session || isNew)) {
    return (
      <div className="max-w-md mx-auto space-y-6">
        <h2 className="text-xl font-bold">登录 - 新建会话</h2>

        <Card>
          <h3 className="font-medium mb-3">密码登录</h3>
          <div className="space-y-3">
            <input
              type="text" placeholder="手机号" value={loginPhone}
              onChange={e => setLoginPhone(e.target.value)}
              className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm"
            />
            <input
              type="password" placeholder="密码" value={loginPasswd}
              onChange={e => setLoginPasswd(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleLogin()}
              className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm"
            />
            {loginError && <p className="text-sm text-destructive">{loginError}</p>}
            <button onClick={handleLogin}
              className="w-full py-2 bg-primary text-primary-foreground rounded-md text-sm font-medium hover:bg-primary/90">
              <LogIn className="w-4 h-4 inline mr-1" /> 登录
            </button>
          </div>
        </Card>

        {savedSessions.length > 0 && (
          <div>
            <h3 className="font-medium mb-2">已保存的会话</h3>
            <div className="space-y-2">
              {savedSessions.map(s => (
                <div key={s.index} className="flex items-center justify-between p-3 border border-border rounded-md">
                  <div>
                    <span className="text-sm font-medium">{s.name}</span>
                    <span className="text-xs text-muted-foreground ml-2">{s.phone}</span>
                  </div>
                  <button
                    onClick={async () => {
                      try {
                        const sid = await resumeSession(s.index)
                        setActiveSid(sid)
                        initSession(sid)
                        await loadCourses(sid)
                        setStep(2)
                      } catch (e) {
                        alert(e instanceof Error ? e.message : '恢复失败')
                      }
                    }}
                    className="text-xs px-3 py-1 bg-primary/10 text-primary rounded-md hover:bg-primary/20"
                  >
                    恢复
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    )
  }

  // Step 2: Select Courses
  if (step === 2 && activeSid) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold">选择课程</h2>
          <span className="text-sm text-muted-foreground">{session?.display_name}</span>
        </div>

        <div className="flex gap-2 flex-wrap">
          <button onClick={() => setSelectedCourses(new Set(courses.map((_, i) => i)))}
            className="text-xs px-3 py-1 border border-border rounded-md hover:bg-accent">全选</button>
          <button onClick={() => setSelectedCourses(new Set(courses.map((c, i) => c.state_value === 0 ? i : -1).filter(i => i >= 0)))}
            className="text-xs px-3 py-1 border border-border rounded-md hover:bg-accent">仅进行中</button>
          <button onClick={() => setSelectedCourses(new Set())}
            className="text-xs px-3 py-1 border border-border rounded-md hover:bg-accent">清空</button>
          <span className="text-xs text-muted-foreground self-center ml-auto">已选 {selectedCourses.size} 门</span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {courses.map(c => (
            <label key={c.index}
              className={`flex items-center gap-3 p-3 rounded-md border cursor-pointer transition-colors ${
                selectedCourses.has(c.index) ? 'border-primary bg-primary/5' : 'border-border hover:bg-accent'
              }`}
            >
              <input type="checkbox" checked={selectedCourses.has(c.index)}
                onChange={() => {
                  const next = new Set(selectedCourses)
                  next.has(c.index) ? next.delete(c.index) : next.add(c.index)
                  setSelectedCourses(next)
                }}
                className="w-4 h-4"
              />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{c.name}</p>
                <p className="text-xs text-muted-foreground">{c.teacher_name}</p>
              </div>
              <span className={`text-xs px-2 py-0.5 rounded ${c.state_value === 0 ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-100 text-gray-600'}`}>
                {c.state}
              </span>
            </label>
          ))}
        </div>

        <div className="flex justify-end">
          <button onClick={() => setStep(3)} disabled={selectedCourses.size === 0}
            className="inline-flex items-center gap-2 px-6 py-2 bg-primary text-primary-foreground rounded-md font-medium disabled:opacity-50 disabled:cursor-not-allowed hover:bg-primary/90">
            下一步 <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    )
  }

  // Step 3: Quick Config
  if (step === 3 && activeSid) {
    return (
      <div className="max-w-lg mx-auto space-y-6">
        <h2 className="text-xl font-bold">任务配置</h2>
        <p className="text-sm text-muted-foreground">已选 {selectedCourses.size} 门课程</p>

        <Card>
          <h3 className="font-medium mb-3">快速开关</h3>
          <div className="space-y-3">
            <ToggleRow label="完成视频任务" checked={overrides.video_enable !== false}
              onChange={v => setOverrides(prev => ({ ...prev, video_enable: v }))} />
            <ToggleRow label="完成测验任务" checked={overrides.work_enable !== false}
              onChange={v => setOverrides(prev => ({ ...prev, work_enable: v }))} />
            <ToggleRow label="完成文档任务" checked={overrides.document_enable !== false}
              onChange={v => setOverrides(prev => ({ ...prev, document_enable: v }))} />
          </div>
        </Card>

        <details className="border border-border rounded-md p-4">
          <summary className="font-medium cursor-pointer">高级选项</summary>
          <div className="mt-3 space-y-3">
            <div>
              <label className="text-xs text-muted-foreground">视频倍速</label>
              <select value={overrides.video_speed || 1} onChange={e => setOverrides(prev => ({ ...prev, video_speed: parseFloat(e.target.value) }))}
                className="w-full px-3 py-1.5 rounded-md border border-input bg-background text-sm mt-1">
                {[0.5, 0.75, 1, 1.25, 1.5, 2, 4, 8, 16].map(s => (
                  <option key={s} value={s}>{s}x</option>
                ))}
              </select>
            </div>
            <ToggleRow label="随机填充兜底" checked={overrides.work_fallback_fuzzer || false}
              onChange={v => setOverrides(prev => ({ ...prev, work_fallback_fuzzer: v }))} />
            <ToggleRow label="考试需确认交卷" checked={overrides.exam_confirm_submit !== false}
              onChange={v => setOverrides(prev => ({ ...prev, exam_confirm_submit: v }))} />
          </div>
        </details>

        <button onClick={handleStartTask}
          className="w-full py-3 bg-primary text-primary-foreground rounded-md font-medium text-lg hover:bg-primary/90 transition-colors">
          <Play className="w-5 h-5 inline mr-2" /> 开始执行
        </button>
        <button onClick={() => setStep(2)} className="w-full text-sm text-muted-foreground hover:text-foreground">
          返回选课
        </button>
      </div>
    )
  }

  // Step 4: Execution
  if (step === 4 && activeSid) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold">{status.course_name || '执行中'}</h2>
            <p className="text-sm text-muted-foreground">步骤: {status.step}</p>
          </div>
          {status.running && (
            <button onClick={handleCancel}
              className="inline-flex items-center gap-1 px-4 py-2 bg-destructive text-destructive-foreground rounded-md text-sm font-medium hover:bg-destructive/90">
              <Square className="w-4 h-4" /> 取消任务
            </button>
          )}
        </div>

        {/* Chapter Progress Tree */}
        {chapters.length > 0 && (
          <Card>
            <h3 className="font-medium mb-3">章节进度 ({chapters.filter(c => c.point_total > 0).length} 个任务章节)</h3>
            <div className="space-y-1">
              {chapters.map(ch => {
                const isHeader = ch.point_total === 0
                const isActive = ch.index === currentChapter
                const pct = ch.point_total > 0 ? Math.round((ch.point_finished / ch.point_total) * 100) : 0
                const isDone = ch.point_total > 0 && ch.point_finished === ch.point_total

                return (
                  <div key={ch.index}
                    className={`flex items-center gap-2 rounded-md px-2 py-1.5 transition-colors ${
                      isActive && !isHeader ? 'bg-primary/10 ring-1 ring-primary/30' : ''
                    }`}
                    style={{ paddingLeft: `${8 + ch.layer * 20}px` }}
                  >
                    {/* Status icon */}
                    <span className="shrink-0 w-4 text-center">
                      {isHeader ? (
                        <span className="text-[10px] text-muted-foreground">&#9654;</span>
                      ) : isDone ? (
                        <span className="text-emerald-500 text-xs">&#10003;</span>
                      ) : isActive ? (
                        <span className="w-2 h-2 bg-primary rounded-full animate-pulse inline-block" />
                      ) : (
                        <span className="w-2 h-2 bg-muted-foreground/30 rounded-full inline-block" />
                      )}
                    </span>

                    {/* Label */}
                    <span className={`text-xs shrink-0 w-10 ${isHeader ? 'text-muted-foreground font-medium' : 'text-foreground/70'}`}>
                      {ch.label}
                    </span>

                    {/* Name */}
                    <span className={`text-sm flex-1 truncate ${isHeader ? 'font-medium text-foreground/80' : 'text-foreground/70'} ${
                      isActive && !isHeader ? 'text-primary font-medium' : ''
                    }`}>
                      {ch.name}
                      {isActive && currentTaskPoint >= 0 && !isHeader && (
                        <span className="text-primary/70 text-xs ml-1">- 任务点 {currentTaskPoint + 1}</span>
                      )}
                    </span>

                    {/* Progress bar (only for non-headers) */}
                    {!isHeader && (
                      <>
                        <div className="w-24 h-1.5 bg-secondary rounded-full overflow-hidden shrink-0">
                          <div
                            className={`h-full rounded-full transition-all duration-500 ${isDone ? 'bg-emerald-500' : isActive ? 'bg-primary' : 'bg-primary/60'}`}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span className={`text-[10px] w-10 text-right shrink-0 ${isDone ? 'text-emerald-500 font-medium' : 'text-muted-foreground'}`}>
                          {isDone ? '完成' : `${ch.point_finished}/${ch.point_total}`}
                        </span>
                      </>
                    )}
                    {isHeader && <div className="w-24 shrink-0" />}
                  </div>
                )
              })}
            </div>
          </Card>
        )}

        {/* Current Activity */}
        <Card>
          <h3 className="font-medium mb-2">当前活动</h3>
          <ActivityDisplay activity={currentActivity} />
        </Card>

        {/* Event Log */}
        <Card>
          <h3 className="font-medium mb-2">事件日志 ({eventLog.length})</h3>
          <div className="max-h-64 overflow-y-auto font-mono text-xs space-y-0.5">
            {eventLog.slice(-100).map((entry, i) => (
              <div key={i} className="flex gap-2">
                <span className="text-muted-foreground shrink-0">
                  {new Date(entry.timestamp).toLocaleTimeString('zh-CN', { hour12: false })}
                </span>
                <span className={entry.type === 'task:error' ? 'text-red-400' : entry.type === 'task:complete' ? 'text-emerald-400' : 'text-foreground/80'}>
                  {entry.message}
                </span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    )
  }

  // Step 5: Result
  if (step === 5 && activeSid) {
    return (
      <div className="max-w-md mx-auto text-center space-y-6 py-12">
        <div className="text-6xl">&#10003;</div>
        <h2 className="text-2xl font-bold">任务完成</h2>
        <p className="text-muted-foreground">会话: {session?.display_name}</p>
        <div className="flex gap-3 justify-center">
          <button onClick={() => { setStep(2); useTaskStore.getState().clearEvents(activeSid) }}
            className="px-6 py-2 bg-primary text-primary-foreground rounded-md font-medium">
            开始新任务
          </button>
          <button onClick={() => navigate('/')}
            className="px-6 py-2 border border-border rounded-md font-medium hover:bg-accent">
            返回仪表盘
          </button>
        </div>
      </div>
    )
  }

  return null
}

function ToggleRow({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center justify-between cursor-pointer">
      <span className="text-sm">{label}</span>
      <button
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`w-9 h-5 rounded-full transition-colors relative ${checked ? 'bg-primary' : 'bg-secondary'}`}
      >
        <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${checked ? 'left-4' : 'left-0.5'}`} />
      </button>
    </label>
  )
}

function ActivityDisplay({ activity }: { activity: { type: string; data: Record<string, unknown> | null } }) {
  if (!activity.data) return <p className="text-sm text-muted-foreground">等待中...</p>

  switch (activity.type) {
    case 'question': {
      const d = activity.data
      const opts = d.options as Record<string, string> | undefined
      return (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-xs px-2 py-0.5 bg-blue-100 text-blue-700 rounded">{d.question_type as string}</span>
            <span className="text-xs text-muted-foreground">第 {d.index as number}/{d.total as number} 题</span>
            <span className={`text-xs font-medium ${d.status ? 'text-emerald-500' : 'text-red-500'}`}>
              {d.status ? '已匹配' : '未匹配'}
            </span>
          </div>
          <p className="text-sm">{d.question_value as string}</p>
          {opts && <div className="text-xs text-muted-foreground space-x-2">
            {Object.entries(opts).map(([k, v]) => (
              <span key={k}>{k}. {v}</span>
            ))}
          </div>}
          <p className="text-sm font-medium text-primary">答案: {d.answer as string || '-'}</p>
        </div>
      )
    }
    case 'video': {
      const d = activity.data
      return (
        <div className="space-y-2">
          <span className="text-xs px-2 py-0.5 bg-purple-100 text-purple-700 rounded">视频播放</span>
          <div className="w-full h-2 bg-secondary rounded-full overflow-hidden">
            <div className="h-full bg-purple-500 rounded-full transition-all" style={{
              width: `${d.duration ? ((d.playing_time as number) / (d.duration as number)) * 100 : 0}%`
            }} />
          </div>
          <div className="flex gap-4 text-xs text-muted-foreground">
            <span>{(d.playing_time as number) || 0}s / {(d.duration as number) || 0}s</span>
            <span>{(d.speed as number) || 1}x</span>
          </div>
        </div>
      )
    }
    case 'wait':
      return <p className="text-sm text-muted-foreground">等待 {activity.data.seconds_remaining as number}s: {activity.data.message as string}</p>
    case 'exam':
      return <p className="text-sm">考试: {activity.data.title as string}</p>
    default:
      return <p className="text-sm text-muted-foreground">未知活动</p>
  }
}
