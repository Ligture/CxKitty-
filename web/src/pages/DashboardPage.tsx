import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import { useDashboardStore } from '@/stores/dashboardStore'
import { useDashboardSocket } from '@/hooks/useSocket'
import { Card } from '@/components/shared/Card'
import {
  Users, Play, CheckCircle, Activity, Plus, LogIn, Trash2,
} from 'lucide-react'

export function DashboardPage() {
  const navigate = useNavigate()
  const { activeSessions, savedSessions, loadSavedSessions, loadActiveSessions, resumeSession, logout } = useAuthStore()
  const { entries } = useDashboardStore()

  useDashboardSocket()

  useEffect(() => {
    loadActiveSessions()
    loadSavedSessions()
  }, [])

  const activeArr = Object.values(activeSessions)
  const runningCount = activeArr.filter(s => s.task_running).length

  const handleResume = async (index: number) => {
    const sid = await resumeSession(index)
    navigate(`/session/${sid}`)
  }

  return (
    <div className="space-y-6">
      {/* Stats Bar */}
      <div className="grid grid-cols-4 gap-4">
        <StatCard icon={Users} label="活跃会话" value={activeArr.length} color="text-blue-500" />
        <StatCard icon={Play} label="运行中" value={runningCount} color="text-emerald-500" />
        <StatCard icon={CheckCircle} label="已完成" value="-" color="text-violet-500" />
        <StatCard icon={Activity} label="事件" value="-" color="text-amber-500" />
      </div>

      {/* Active Sessions */}
      <div>
        <h3 className="text-lg font-semibold mb-3">活跃会话</h3>
        {activeArr.length === 0 ? (
          <div className="text-center py-12 border border-dashed border-border rounded-lg">
            <p className="text-muted-foreground mb-3">暂无可用的活动会话</p>
            <button
              onClick={() => navigate('/session/new')}
              className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-md text-sm font-medium hover:bg-primary/90 transition-colors"
            >
              <Plus className="w-4 h-4" /> 添加会话
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {activeArr.map(session => {
              const entry = entries[session.session_id]
              return (
                <Card key={session.session_id} className="hover:border-primary/50 transition-colors cursor-pointer"
                  onClick={() => navigate(`/session/${session.session_id}`)}>
                  <div className="flex items-start justify-between mb-3">
                    <div>
                      <h4 className="font-medium">{session.display_name}</h4>
                      <p className="text-xs text-muted-foreground">{session.session_id}</p>
                    </div>
                    <span className={`w-2 h-2 rounded-full ${session.task_running ? 'bg-emerald-500 animate-pulse' : 'bg-gray-400'}`} />
                  </div>
                  <div className="text-sm text-muted-foreground space-y-1">
                    <div>登录方式: {session.login_method}</div>
                    {session.task_running && (
                      <>
                        <div>课程: {session.task_course_name || '-'}</div>
                        <div>步骤: {entry?.step || session.task_step || '-'}</div>
                      </>
                    )}
                  </div>
                  <div className="flex gap-2 mt-3">
                    <button
                      onClick={(e) => { e.stopPropagation(); navigate(`/session/${session.session_id}`) }}
                      className="text-xs px-3 py-1 bg-primary/10 text-primary rounded-md hover:bg-primary/20"
                    >
                      进入
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); logout(session.session_id) }}
                      className="text-xs px-3 py-1 bg-destructive/10 text-destructive rounded-md hover:bg-destructive/20"
                    >
                      注销
                    </button>
                  </div>
                </Card>
              )
            })}
            {/* Add New Session Card */}
            <button
              onClick={() => navigate('/session/new')}
              className="border-2 border-dashed border-border rounded-lg p-6 flex flex-col items-center justify-center gap-2 text-muted-foreground hover:border-primary/50 hover:text-primary transition-colors min-h-[160px]"
            >
              <Plus className="w-8 h-8" />
              <span className="text-sm font-medium">添加会话</span>
            </button>
          </div>
        )}
      </div>

      {/* Saved Sessions */}
      <div>
        <h3 className="text-lg font-semibold mb-3">已保存的登录会话</h3>
        {savedSessions.length === 0 ? (
          <p className="text-muted-foreground text-sm">暂无已保存的会话</p>
        ) : (
          <div className="space-y-2">
            {savedSessions.map(s => (
              <div key={s.index} className="flex items-center justify-between p-3 border border-border rounded-md bg-card">
                <div>
                  <span className="font-medium text-sm">{s.name}</span>
                  <span className="text-xs text-muted-foreground ml-2">{s.phone}</span>
                  {s.has_passwd && <span className="text-xs text-emerald-500 ml-2">有密码</span>}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => handleResume(s.index)}
                    className="inline-flex items-center gap-1 text-xs px-3 py-1 bg-primary/10 text-primary rounded-md hover:bg-primary/20"
                  >
                    <LogIn className="w-3 h-3" /> 恢复
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function StatCard({ icon: Icon, label, value, color }: {
  icon: React.ElementType; label: string; value: number | string; color: string
}) {
  return (
    <div className="p-4 rounded-lg border border-border bg-card">
      <div className="flex items-center gap-3">
        <Icon className={`w-5 h-5 ${color}`} />
        <div>
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="text-2xl font-bold">{value}</p>
        </div>
      </div>
    </div>
  )
}
