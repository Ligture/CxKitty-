import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { Card } from '@/components/shared/Card'
import type { LogFile } from '@/types/api'

export function LogsPage() {
  const [files, setFiles] = useState<LogFile[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [content, setContent] = useState<string>('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api.get<LogFile[]>('/logs').then(setFiles).catch(() => {})
  }, [])

  const loadFile = async (filename: string) => {
    setSelected(filename)
    setLoading(true)
    try {
      const data = await api.get<{ content: string }>(`/logs/${filename}`)
      setContent(data.content)
    } catch {
      setContent('加载失败')
    }
    setLoading(false)
  }

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-bold">日志浏览</h2>

      <div className="flex gap-4 h-[calc(100vh-12rem)]">
        {/* File List */}
        <div className="w-64 shrink-0 border border-border rounded-md overflow-auto bg-card">
          <div className="p-3 border-b border-border font-medium text-sm">日志文件</div>
          {files.length === 0 ? (
            <p className="p-3 text-sm text-muted-foreground">暂无日志文件</p>
          ) : (
            files.map(f => (
              <button key={f.name} onClick={() => loadFile(f.name)}
                className={`w-full text-left px-3 py-2 text-sm hover:bg-accent transition-colors ${
                  selected === f.name ? 'bg-primary/10 text-primary' : ''
                }`}
              >
                <div className="truncate">{f.name}</div>
                <div className="text-xs text-muted-foreground">{formatSize(f.size)}</div>
              </button>
            ))
          )}
        </div>

        {/* Content Viewer */}
        <div className="flex-1 border border-border rounded-md bg-zinc-950 overflow-hidden flex flex-col">
          <div className="p-2 border-b border-border text-xs text-muted-foreground">
            {selected || '选择日志文件'}
          </div>
          <div className="flex-1 overflow-auto p-4">
            {loading ? (
              <p className="text-muted-foreground text-sm">加载中...</p>
            ) : (
              <pre className="font-mono text-xs text-emerald-400 whitespace-pre-wrap">{content || '选择左侧文件查看'}</pre>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
