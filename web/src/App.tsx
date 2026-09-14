import { Routes, Route } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { DashboardPage } from '@/pages/DashboardPage'
import { SessionPage } from '@/pages/SessionPage'
import { ConfigPage } from '@/pages/ConfigPage'
import { LogsPage } from '@/pages/LogsPage'

function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/session/:sessionId" element={<SessionPage />} />
        <Route path="/config" element={<ConfigPage />} />
        <Route path="/logs" element={<LogsPage />} />
      </Routes>
    </AppShell>
  )
}

export default App
