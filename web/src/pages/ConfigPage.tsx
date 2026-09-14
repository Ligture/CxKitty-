import { useEffect, useState } from 'react'
import { useConfigStore } from '@/stores/configStore'
import { api } from '@/lib/api'
import { Card } from '@/components/shared/Card'
import type { SearcherTemplate, SearcherField } from '@/types/api'
import { Plus, Trash2, Settings, X } from 'lucide-react'

export function ConfigPage() {
  const { config, searcherTemplates, loading, loadConfig, loadSearcherTemplates, saveSection } = useConfigStore()
  const [tab, setTab] = useState('basic')

  useEffect(() => { loadConfig(); loadSearcherTemplates() }, [])

  if (loading || !config) {
    return <div className="flex items-center justify-center h-64"><p className="text-muted-foreground">加载中...</p></div>
  }

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold">配置中心</h2>

      <div className="flex gap-2 border-b border-border">
        {[
          { key: 'basic', label: '基本设置' },
          { key: 'proxy', label: '代理' },
          { key: 'tasks', label: '任务参数' },
          { key: 'searchers', label: '搜索器管理' },
        ].map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === t.key ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
          >{t.label}</button>
        ))}
      </div>

      {tab === 'basic' && (
        <Card>
          <h3 className="font-medium mb-4">基本设置</h3>
          <ConfigToggle label="多会话模式" configKey="multi_session" config={config} onChange={() => {}} />
          <ConfigToggle label="账号脱敏" configKey="mask_acc" config={config} onChange={() => {}} />
          <ConfigToggle label="预获取人脸" configKey="fetch_uploaded_face" config={config} onChange={() => {}} />
        </Card>
      )}

      {tab === 'proxy' && (
        <Card>
          <h3 className="font-medium mb-4">代理设置</h3>
          <ConfigToggle label="启用代理" configKey="proxies.enable" config={config}
            onChange={v => { const p = { ...(config.proxies as Record<string, unknown>), enable: v }; saveSection('proxies', p) }} />
          <ConfigInput label="HTTP 代理" configKey="proxies.HTTP" config={config}
            onChange={v => { const p = { ...(config.proxies as Record<string, unknown>), HTTP: v }; saveSection('proxies', p) }} />
        </Card>
      )}

      {tab === 'tasks' && (
        <div className="grid grid-cols-2 gap-4">
          {['video', 'work', 'document', 'exam'].map(section => (
            <Card key={section}>
              <h4 className="font-medium capitalize mb-3">{section}</h4>
              {Object.entries((config[section] as Record<string, unknown>) || {}).map(([key, val]) => (
                typeof val === 'boolean' ? (
                  <ConfigToggle key={key} label={key} configKey={`${section}.${key}`} config={config}
                    onChange={v => saveSection(section, { ...(config[section] as object), [key]: v })} />
                ) : (
                  <ConfigInput key={key} label={key} configKey={`${section}.${key}`} config={config}
                    onChange={v => saveSection(section, { ...(config[section] as object), [key]: typeof val === 'number' ? Number(v) : v })} />
                )
              ))}
            </Card>
          ))}
        </div>
      )}

      {tab === 'searchers' && <SearcherManager />}
    </div>
  )
}

// ─── Searcher Manager ────────────────────────────────────────────

function SearcherManager() {
  const { config, searcherTemplates, loadConfig } = useConfigStore()
  const [showAdd, setShowAdd] = useState(false)
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null)
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)

  const searchers = (config?.searchers as Array<Record<string, unknown>>) || []

  const handleToggle = async (index: number) => {
    const updated = searchers.map((s, i) => ({
      ...s,
      enabled: i === index ? true : false,
    }))
    await saveAll(updated)
  }

  const handleAdd = async (formData: Record<string, unknown>) => {
    const updated = [...searchers, formData]
    await saveAll(updated)
    setShowAdd(false)
    setSelectedTemplate(null)
  }

  const handleUpdate = async (index: number, formData: Record<string, unknown>) => {
    const updated = [...searchers]
    updated[index] = formData
    await saveAll(updated)
    setEditingIndex(null)
  }

  const handleDelete = async (index: number) => {
    const updated = searchers.filter((_, i) => i !== index)
    await saveAll(updated)
  }

  const saveAll = async (list: Record<string, unknown>[]) => {
    setSaving(true)
    try {
      await api.put('/searchers', list)
      await loadConfig()
    } catch (e) {
      alert('保存失败: ' + (e instanceof Error ? e.message : ''))
    }
    setSaving(false)
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-medium">搜索器管理</h3>
          <p className="text-xs text-muted-foreground mt-1">启用一个搜索器作为答题来源</p>
        </div>
        <button onClick={() => setShowAdd(true)}
          className="inline-flex items-center gap-1 px-3 py-1.5 bg-primary text-primary-foreground rounded-md text-sm font-medium hover:bg-primary/90">
          <Plus className="w-4 h-4" /> 添加搜索器
        </button>
      </div>

      {searchers.length === 0 && (
        <div className="text-center py-12 border border-dashed border-border rounded-lg">
          <p className="text-muted-foreground mb-2">暂无搜索器</p>
          <button onClick={() => setShowAdd(true)}
            className="text-sm text-primary hover:underline">添加第一个搜索器</button>
        </div>
      )}

      <div className="space-y-2">
        {searchers.map((s, i) => (
          <SearcherCard
            key={i}
            index={i}
            searcher={s}
            isEditing={editingIndex === i}
            templates={searcherTemplates}
            onToggle={() => handleToggle(i)}
            onEdit={() => setEditingIndex(i)}
            onCancelEdit={() => setEditingIndex(null)}
            onSave={(data) => handleUpdate(i, data)}
            onDelete={() => handleDelete(i)}
          />
        ))}
      </div>

      {saving && <p className="text-xs text-muted-foreground">保存中...</p>}

      {/* Add Searcher Modal */}
      {showAdd && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => { setShowAdd(false); setSelectedTemplate(null) }}>
          <div className="bg-card border border-border rounded-lg p-6 w-full max-w-lg max-h-[80vh] overflow-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold">添加搜索器</h3>
              <button onClick={() => { setShowAdd(false); setSelectedTemplate(null) }} className="text-muted-foreground hover:text-foreground"><X className="w-5 h-5" /></button>
            </div>

            {!selectedTemplate ? (
              <div className="grid grid-cols-2 gap-2">
                {Object.entries(searcherTemplates).map(([key, tmpl]) => (
                  <button key={key}
                    onClick={() => setSelectedTemplate(key)}
                    className="text-left p-3 border border-border rounded-md hover:border-primary hover:bg-primary/5 transition-colors"
                  >
                    <div className="font-medium text-sm">{tmpl.label}</div>
                    <div className="text-xs text-muted-foreground mt-1">{tmpl.desc}</div>
                  </button>
                ))}
              </div>
            ) : (
              <SearcherForm
                templateKey={selectedTemplate}
                template={searcherTemplates[selectedTemplate]}
                onSave={handleAdd}
                onCancel={() => setSelectedTemplate(null)}
              />
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Searcher Card ───────────────────────────────────────────────

function SearcherCard({ index, searcher, isEditing, templates, onToggle, onEdit, onCancelEdit, onSave, onDelete }: {
  index: number
  searcher: Record<string, unknown>
  isEditing: boolean
  templates: Record<string, SearcherTemplate>
  onToggle: () => void
  onEdit: () => void
  onCancelEdit: () => void
  onSave: (data: Record<string, unknown>) => void
  onDelete: () => void
}) {
  const type = searcher.type as string
  const tmpl = templates[type]
  const enabled = !!searcher.enabled

  return (
    <div className={`border rounded-md p-3 transition-colors ${enabled ? 'border-primary bg-primary/5' : 'border-border'}`}>
      {isEditing ? (
        <SearcherForm
          templateKey={type}
          template={tmpl}
          initialData={searcher}
          onSave={onSave}
          onCancel={onCancelEdit}
        />
      ) : (
        <div className="flex items-center gap-3">
          {/* Enable toggle */}
          <button onClick={onToggle} className="shrink-0">
            <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center transition-colors ${
              enabled ? 'border-primary bg-primary' : 'border-muted-foreground/30'
            }`}>
              {enabled && <div className="w-2 h-2 rounded-full bg-white" />}
            </div>
          </button>

          {/* Info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-medium text-sm">{tmpl?.label || type}</span>
              {enabled && <span className="text-xs px-1.5 py-0.5 bg-primary/20 text-primary rounded">已启用</span>}
            </div>
            <div className="text-xs text-muted-foreground truncate">
              {[searcher.model, searcher.base_url, searcher.url]
                .filter(Boolean)
                .map(v => String(v))
                .join('  ') || '点击编辑配置'}
            </div>
            {searcher.note ? (
              <div className="text-xs text-muted-foreground/70 truncate mt-0.5 italic">
                {String(searcher.note)}
              </div>
            ) : null}
          </div>

          {/* Actions */}
          <button onClick={onEdit} className="p-1 text-muted-foreground hover:text-foreground transition-colors" title="编辑">
            <Settings className="w-4 h-4" />
          </button>
          <button onClick={onDelete} className="p-1 text-muted-foreground hover:text-destructive transition-colors" title="删除">
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  )
}

// ─── Searcher Form ───────────────────────────────────────────────

function SearcherForm({ templateKey, template, initialData, onSave, onCancel }: {
  templateKey: string
  template: SearcherTemplate | undefined
  initialData?: Record<string, unknown>
  onSave: (data: Record<string, unknown>) => void
  onCancel: () => void
}) {
  const [form, setForm] = useState<Record<string, unknown>>(() => {
    if (initialData) return { ...initialData }
    const defaults: Record<string, unknown> = {}
    if (template) {
      for (const f of template.fields) {
        defaults[f.key] = f.default
      }
    }
    return defaults
  })

  const handleSubmit = () => {
    onSave(form)
  }

  const setField = (key: string, value: unknown) => {
    setForm(prev => ({ ...prev, [key]: value }))
  }

  if (!template) {
    return <div className="text-sm text-muted-foreground">模板未找到: {templateKey}</div>
  }

  return (
    <div className="space-y-3">
      <h4 className="font-medium text-sm">{template.label}</h4>
      {template.fields.filter(f => f.type !== 'hidden').map(f => (
        <div key={f.key}>
          <label className="text-xs text-muted-foreground mb-1 block">
            {f.label} {f.required ? <span className="text-destructive">*</span> : null}
          </label>
          {f.type === 'text' || f.type === 'url' ? (
            <input type="text" value={String(form[f.key] ?? '')} placeholder={f.placeholder}
              onChange={e => setField(f.key, e.target.value)}
              className="w-full px-2 py-1.5 rounded border border-input bg-background text-sm" />
          ) : f.type === 'password' ? (
            <input type="password" value={String(form[f.key] ?? '')} placeholder={f.placeholder}
              onChange={e => setField(f.key, e.target.value)}
              className="w-full px-2 py-1.5 rounded border border-input bg-background text-sm" />
          ) : f.type === 'number' ? (
            <input type="number" value={Number(form[f.key] ?? 0)}
              onChange={e => setField(f.key, Number(e.target.value))}
              className="w-full px-2 py-1.5 rounded border border-input bg-background text-sm" />
          ) : f.type === 'select' && f.options ? (
            <select value={String(form[f.key] ?? f.default)} onChange={e => setField(f.key, e.target.value)}
              className="w-full px-2 py-1.5 rounded border border-input bg-background text-sm">
              {f.options.map(opt => <option key={opt} value={opt}>{opt}</option>)}
            </select>
          ) : f.type === 'switch' ? (
            <label className="flex items-center gap-2 cursor-pointer">
              <button role="switch" aria-checked={!!form[f.key]}
                onClick={() => setField(f.key, !form[f.key])}
                className={`w-8 h-4 rounded-full transition-colors relative ${form[f.key] ? 'bg-primary' : 'bg-secondary'}`}>
                <span className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-transform ${form[f.key] ? 'left-4' : 'left-0.5'}`} />
              </button>
              <span className="text-xs text-muted-foreground">{f.help || f.label}</span>
            </label>
          ) : f.type === 'textarea' ? (
            <textarea value={String(form[f.key] ?? '')} rows={f.rows || 3} placeholder={f.placeholder}
              onChange={e => setField(f.key, e.target.value)}
              className="w-full px-2 py-1.5 rounded border border-input bg-background text-sm font-mono resize-y" />
          ) : null}
          {f.help && f.type !== 'switch' && <p className="text-xs text-muted-foreground mt-0.5">{f.help}</p>}
        </div>
      ))}
      <div className="flex gap-2 justify-end pt-2">
        <button onClick={onCancel}
          className="px-3 py-1.5 border border-border rounded-md text-sm hover:bg-accent">取消</button>
        <button onClick={handleSubmit}
          className="px-4 py-1.5 bg-primary text-primary-foreground rounded-md text-sm font-medium hover:bg-primary/90">保存</button>
      </div>
    </div>
  )
}

// ─── Shared form helpers ─────────────────────────────────────────

function ConfigToggle({ label, configKey, config, onChange }: {
  label: string; configKey: string; config: Record<string, unknown>; onChange: (v: boolean) => void
}) {
  const val = getValue(config, configKey)
  const checked = typeof val === 'boolean' ? val : false
  return (
    <label className="flex items-center justify-between py-2 cursor-pointer">
      <span className="text-sm">{label}</span>
      <button role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
        className={`w-9 h-5 rounded-full transition-colors relative ${checked ? 'bg-primary' : 'bg-secondary'}`}>
        <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${checked ? 'left-4' : 'left-0.5'}`} />
      </button>
    </label>
  )
}

function ConfigInput({ label, configKey, config, onChange }: {
  label: string; configKey: string; config: Record<string, unknown>; onChange: (v: string | number) => void
}) {
  const val = getValue(config, configKey)
  return (
    <div className="flex items-center justify-between py-2 gap-3">
      <span className="text-sm shrink-0">{label}</span>
      <input type={typeof val === 'number' ? 'number' : 'text'}
        value={val !== undefined ? String(val) : ''}
        onChange={e => onChange(typeof val === 'number' ? Number(e.target.value) : e.target.value)}
        className="w-40 px-2 py-1 rounded border border-input bg-background text-sm text-right font-mono"
      />
    </div>
  )
}

function getValue(obj: Record<string, unknown>, path: string): unknown {
  const parts = path.split('.')
  let current: unknown = obj
  for (const p of parts) {
    if (current && typeof current === 'object') current = (current as Record<string, unknown>)[p]
    else return undefined
  }
  return current
}
