import type { Asset, ComfySettings, Job, Preset, Project, PromptMode, Render, ServiceStatus, Shot } from './types'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init)
  const text = await resp.text()
  let data: unknown = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = text
  }
  if (!resp.ok) {
    const detail =
      data && typeof data === 'object' && 'detail' in data
        ? String((data as { detail: unknown }).detail)
        : String(data || resp.statusText)
    throw new Error(detail)
  }
  return data as T
}

export const api = {
  health: () => request<{ ok: boolean }>('/api/health'),

  serviceStatus: () => request<ServiceStatus>('/api/service/status'),
  serviceStart: () => request<{ ok: boolean; message: string }>('/api/service/start', { method: 'POST' }),
  serviceStop: () => request<{ ok: boolean; message: string }>('/api/service/stop', { method: 'POST' }),
  serviceRestart: () => request<{ ok: boolean; message: string }>('/api/service/restart', { method: 'POST' }),
  serviceFree: () => request<{ ok: boolean; message: string }>('/api/service/free', { method: 'POST' }),
  serviceLogs: (lines = 200) => request<{ text: string }>(`/api/service/logs?lines=${lines}`),

  comfySettings: () => request<ComfySettings>('/api/settings/comfy'),
  saveComfySettings: (mode: string, base_url: string, token?: string) =>
    request<ComfySettings>('/api/settings/comfy', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode, base_url, token }),
    }),
  testComfy: (base_url: string, token?: string) =>
    request<{ ok: boolean; error?: string; latency_ms?: number; base_url: string; system?: Record<string, unknown>; devices?: Array<{ name?: string; vram_total?: number; vram_free?: number }> }>(
      '/api/settings/comfy/test',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ base_url, token }),
      },
    ),
  resetComfySettings: () => request<ComfySettings>('/api/settings/comfy', { method: 'DELETE' }),

  presets: () => request<{ items: Preset[] }>('/api/presets'),

  upload: async (file: File, kind: string) => {
    const form = new FormData()
    form.append('file', file)
    form.append('kind', kind)
    return request<Asset>('/api/assets/upload', { method: 'POST', body: form })
  },

  createJob: (preset_id: string, inputs: Record<string, unknown>) =>
    request<Job>('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preset_id, inputs }),
    }),
  jobs: (limit = 30) => request<{ items: Job[] }>(`/api/jobs?limit=${limit}`),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  cancelJob: (id: string) => request<{ ok: boolean }>(`/api/jobs/${id}/cancel`, { method: 'POST' }),
  retryJob: (id: string) => request<Job>(`/api/jobs/${id}/retry`, { method: 'POST' }),

  promptModes: () => request<{ items: PromptMode[]; ai_configured: boolean; model: string }>('/api/prompt/modes'),  rewrite: (mode: string, brief: string) =>
    request<{ ok: boolean; content: string }>('/api/prompt/rewrite', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode, brief }),
    }),

  asset: (id: string) => request<Asset>(`/api/assets/${id}`),

  projects: () => request<{ items: Project[] }>('/api/projects'),
  createProject: (name: string, style = '') =>
    request<Project>('/api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, style }),
    }),
  deleteProject: (id: string) => request<{ ok: boolean }>(`/api/projects/${id}`, { method: 'DELETE' }),

  shots: (projectId: string) => request<{ items: Shot[] }>(`/api/projects/${projectId}/shots`),
  createShot: (project_id: string, title: string, preset_id: string) =>
    request<Shot>('/api/shots', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id, title, preset_id }),
    }),
  patchShot: (id: string, patch: Partial<Pick<Shot, 'title' | 'preset_id' | 'values' | 'idx'>>) =>
    request<Shot>(`/api/shots/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }),
  deleteShot: (id: string) => request<{ ok: boolean }>(`/api/shots/${id}`, { method: 'DELETE' }),
  generateShot: (id: string, values: Record<string, unknown>) =>
    request<Job>(`/api/shots/${id}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ values }),
    }),
  takes: (id: string) => request<{ items: Job[] }>(`/api/shots/${id}/takes`),

  ffmpegStatus: () => request<{ available: boolean; ffmpeg: string; ffprobe: string; hint: string }>('/api/ffmpeg/status'),
  createRender: (projectId: string, shot_ids: string[], options: { width: number; height: number; fps: number }) =>
    request<Render>(`/api/projects/${projectId}/renders`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ shot_ids, options }),
    }),
  renders: (projectId: string) => request<{ items: Render[] }>(`/api/projects/${projectId}/renders`),
  render: (id: string) => request<Render>(`/api/renders/${id}`),
  deleteRender: (id: string) => request<{ ok: boolean }>(`/api/renders/${id}`, { method: 'DELETE' }),
}

export function formatDuration(seconds?: number): string {
  if (!seconds || seconds < 0) return '—'
  const s = Math.floor(seconds)
  if (s < 60) return `${s} 秒`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} 分 ${s % 60} 秒`
  return `${Math.floor(m / 60)} 小时 ${m % 60} 分`
}

export function formatBytes(size?: number): string {
  if (!size) return '—'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = size
  let i = 0
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024
    i += 1
  }
  return `${value.toFixed(value >= 10 || i === 0 ? 0 : 1)} ${units[i]}`
}

export function timeAgo(ts?: number): string {
  if (!ts) return '—'
  const diff = Date.now() / 1000 - ts
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  return `${Math.floor(diff / 86400)} 天前`
}
