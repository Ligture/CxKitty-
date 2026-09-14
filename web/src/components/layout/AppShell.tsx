import { useEffect } from 'react'
import { NavLink } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import { useSocketConnected } from '@/hooks/useSocket'
import { LayoutDashboard, Play, Settings, FileText } from 'lucide-react'

export function AppShell({ children }: { children: React.ReactNode }) {
  const connected = useSocketConnected()
  const { activeSessions, loadActiveSessions } = useAuthStore()

  useEffect(() => { loadActiveSessions() }, [])

  const sessionCount = Object.keys(activeSessions).length

  return (
    <div className="flex h-screen bg-background">
      <aside className="w-56 border-r border-border bg-card flex flex-col shrink-0">
        <div className="p-4 border-b border-border">
          <h1 className="text-lg font-bold text-primary">CxKitty</h1>
          <p className="text-xs text-muted-foreground">超星学习通 · 多会话控制台</p>
        </div>

        <nav className="flex-1 p-2 space-y-1">
          <NavItem to="/" icon={LayoutDashboard} label="仪表盘" />
          <NavItem to="/session/new" icon={Play} label="新建会话" />
          <NavItem to="/config" icon={Settings} label="配置" />
          <NavItem to="/logs" icon={FileText} label="日志" />
        </nav>

        <div className="p-3 border-t border-border">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className={`w-2 h-2 rounded-full ${connected ? 'bg-emerald-500' : 'bg-red-500'}`} />
            {connected ? '已连接' : '未连接'}
          </div>
        </div>
      </aside>

      <div className="flex-1 flex flex-col overflow-hidden">
        <header className="h-12 border-b border-border flex items-center px-4 bg-card shrink-0">
          <h2 className="text-sm font-medium text-muted-foreground">CxKitty v2.0</h2>
          <div className="flex-1" />
          <span className="text-xs text-muted-foreground">{sessionCount} 个活跃会话</span>
        </header>
        <main className="flex-1 overflow-auto p-6">{children}</main>
      </div>
    </div>
  )
}

function NavItem({ to, icon: Icon, label }: { to: string; icon: React.ElementType; label: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
          isActive
            ? 'bg-primary/10 text-primary font-medium'
            : 'text-foreground/70 hover:bg-accent hover:text-foreground'
        }`
      }
    >
      <Icon className="w-4 h-4" />
      {label}
    </NavLink>
  )
}
