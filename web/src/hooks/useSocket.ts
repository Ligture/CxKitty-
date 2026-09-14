import { useEffect, useState } from 'react'
import { getSocket } from '@/lib/socket'
import { useTaskStore } from '@/stores/taskStore'
import { useDashboardStore } from '@/stores/dashboardStore'

export function useSessionSocket(sessionId: string | undefined) {
  const socket = getSocket()
  const { updateFromSocket } = useTaskStore()

  useEffect(() => {
    if (!sessionId) return
    if (!socket.connected) socket.connect()

    socket.emit('join_session', { session_id: sessionId })

    const handler = (ev: string) => (data: Record<string, unknown>) => {
      if (data.session_id === sessionId) {
        updateFromSocket(sessionId, ev, data)
      }
    }

    const events = [
      'task:progress', 'task:question', 'task:question_submit',
      'task:video', 'task:video_report', 'task:captcha', 'task:face',
      'task:wait', 'task:exam_meta', 'task:exam_exported',
      'task:confirm_needed', 'task:complete', 'task:error',
    ]

    const listeners: [string, (data: Record<string, unknown>) => void][] = []
    for (const ev of events) {
      const h = handler(ev)
      listeners.push([ev, h])
      socket.on(ev, h)
    }

    return () => {
      socket.emit('leave_session', { session_id: sessionId })
      for (const [ev, h] of listeners) socket.off(ev, h)
    }
  }, [sessionId])
}

export function useDashboardSocket() {
  const socket = getSocket()
  const { updateFromSocket } = useDashboardStore()

  useEffect(() => {
    if (!socket.connected) socket.connect()
    socket.emit('join_dashboard')

    const onUpdate = (data: Record<string, unknown>) => updateFromSocket(data)
    socket.on('dashboard:update', onUpdate)
    return () => { socket.off('dashboard:update', onUpdate) }
  }, [])
}

export function useSocketConnected() {
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    const socket = getSocket()
    const onConnect = () => setConnected(true)
    const onDisconnect = () => setConnected(false)
    socket.on('connect', onConnect)
    socket.on('disconnect', onDisconnect)
    setConnected(socket.connected)
    return () => { socket.off('connect', onConnect); socket.off('disconnect', onDisconnect) }
  }, [])

  return connected
}
