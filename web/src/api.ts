import type { Asset, ComfySettings, Job, JobsPage, ModelCheckResult, Preset, Project, PromptMode, Render, ServiceStatus, Shot } from './types'

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

  assets: (kind?: string, limit = 24) =>
    request<{ items: Asset[] }>(`/api/assets?limit=${limit}${kind ? `&kind=${kind}` : ''}`),

  createJob: (preset_id: string, inputs: Record<string, unknown>) =>
    request<Job>('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preset_id, inputs }),
    }),
  jobs: (limit = 20, status?: string, cursor?: string | null) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (status) params.set('status', status)
    if (cursor) params.set('cursor', cursor)
    return request<JobsPage>(`/api/jobs?${params.toString()}`)
  },
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  cancelJob: (id: string) => request<{ ok: boolean }>(`/api/jobs/${id}/cancel`, { method: 'POST' }),
  retryJob: (id: string) => request<Job>(`/api/jobs/${id}/retry`, { method: 'POST' }),
  saveJobAsShot: (jobId: string, project_id: string, title: string) =>
    request<Shot>(`/api/jobs/${jobId}/save-as-shot`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id, title }),
    }),

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
  shot: (id: string) => request<Shot>(`/api/shots/${id}`),
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

  modelsCheck: (cardId?: string) =>
    request<ModelCheckResult>(`/api/models/check${cardId ? `?card_id=${cardId}` : ''}`),

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

const PROMPT_ORDER = [
  'subject_definitions',
  'summary',
  'retention_analysis',
  'detailed_description',
  'overall_soundscape',
  'non_diegetic_music',
]

export function formatPrompt(raw: string): string {
  const text = (raw || "").trim().replace(/^```(?:json)?/i, "").replace(/```$/, "").trim()
  let data: unknown
  try { data = JSON.parse(text) } catch { return raw }
  if (!data || typeof data !== 'object' || Array.isArray(data)) return raw
  const obj = data as Record<string, unknown>
  const keys = [...PROMPT_ORDER.filter((k) => k in obj), ...Object.keys(obj).filter((k) => !PROMPT_ORDER.includes(k))]
  return keys.map((key) => {
    const value = obj[key]
    const body = Array.isArray(value) ? value.map(String).filter(Boolean).join('\\n') : typeof value === 'string' ? value : JSON.stringify(value)
    return key + ":\\n" + body
  }).join('\\n\\n')
}

export interface StreamHandlers {
  onDelta: (text: string) => void
  onDone: (content: string) => void
  onError: (message: string) => void
}

export async function rewriteStream(
  mode: string,
  brief: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch('/api/prompt/rewrite/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode, brief }),
    signal,
  })
  if (!resp.ok) {
    const text = await resp.text()
    let message = text || '请求失败'
    try { message = JSON.parse(text).detail || message } catch { /* ignore */ }
    handlers.onError(message)
    return
  }
  if (!resp.body) {
    handlers.onError('当前浏览器不支持流式响应')
    return
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  let acc = ""
  let finished = false
  while (!finished) {
    const { value, done } = await reader.read()
    if (value) buffer += decoder.decode(value, { stream: true })
    let idx = buffer.indexOf('\n\n')
    while (idx !== -1) {
      const block = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      let event = "message"
      const data: string[] = []
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim()
        else if (line.startsWith("data:")) data.push(line.slice(5).trim())
      }
      if (data.length) {
        const payload = data.join("\n")
        if (event === "error") {
          try { handlers.onError(JSON.parse(payload).message) } catch { handlers.onError(payload) }
          return
        }
        if (payload.indexOf("DONE") !== -1) { finished = true; break }
        try {
          const obj = JSON.parse(payload)
          const delta = obj.choices && obj.choices[0] && obj.choices[0].delta && obj.choices[0].delta.content
          if (delta) { acc += delta; handlers.onDelta(delta) }
        } catch { /* ignore */ }
      }
      idx = buffer.indexOf("\n\n")
    }
    if (done) break
  }
  handlers.onDone(formatPrompt(acc))
}
