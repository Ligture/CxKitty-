import { create } from 'zustand'
import { api } from '@/lib/api'
import type { SearcherTemplate } from '@/types/api'

interface ConfigState {
  config: Record<string, unknown> | null
  searcherTemplates: Record<string, SearcherTemplate>
  loading: boolean

  loadConfig: () => Promise<void>
  saveConfig: (data: Record<string, unknown>) => Promise<void>
  saveSection: (section: string, data: unknown) => Promise<void>
  loadSearcherTemplates: () => Promise<void>
}

export const useConfigStore = create<ConfigState>((set, get) => ({
  config: null,
  searcherTemplates: {},
  loading: false,

  loadConfig: async () => {
    set({ loading: true })
    try {
      const data = await api.get<Record<string, unknown>>('/config')
      set({ config: data, loading: false })
    } catch {
      set({ loading: false })
    }
  },

  saveConfig: async (data) => {
    await api.put('/config', data)
    set({ config: data })
  },

  saveSection: async (section, data) => {
    await api.patch(`/config/section/${section}`, data)
    const config = { ...get().config, [section]: data } as Record<string, unknown>
    set({ config })
  },

  loadSearcherTemplates: async () => {
    const data = await api.get<Record<string, SearcherTemplate>>('/searchers/templates')
    set({ searcherTemplates: data })
  },
}))
