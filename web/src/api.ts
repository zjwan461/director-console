import type { Asset, AssetUsage, ComfySettings, Job, JobsPage, ModelCheckResult, ModelInventory, Preset, Project, PromptMode, Render, ServiceStatus, Shot } from './types'

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

  aiSettings: () =>
    request<{ base_url: string; model: string; proxy: string; vision_model: string; key_set: boolean; key_hint: string; overridden: boolean }>(
      '/api/settings/ai',
    ),
  saveAiSettings: (payload: { base_url: string; api_key?: string; model: string; proxy?: string; vision_model?: string }) =>
    request<{ base_url: string; model: string; key_set: boolean; key_hint: string }>('/api/settings/ai', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  resetAiSettings: () => request<unknown>('/api/settings/ai/reset', { method: 'POST' }),
  testAiSettings: (payload: { base_url: string; api_key?: string; model: string; proxy?: string }) =>
    request<{ ok: boolean; latency_ms?: number; error?: string; model_count?: number }>('/api/settings/ai/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  asrSettings: () =>
    request<{ base_url: string; model: string; proxy: string; key_set: boolean; key_hint: string; available: boolean; overridden: boolean }>(
      '/api/settings/asr',
    ),
  saveAsrSettings: (payload: { base_url: string; api_key?: string; model: string; proxy?: string }) =>
    request<{ base_url: string; model: string; key_set: boolean; key_hint: string; available: boolean }>('/api/settings/asr', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  aiScript: (payload: { shot_id: string; kind: 'subtitle' | 'narration'; mode?: string; narration?: string; frames?: number; style?: Record<string, string> }) =>
    request<{ text: string; chars: number; budget: number; over: boolean; compressed: boolean; original_chars: number; duration: number; skip?: string; reason?: string; transcribed?: boolean; followed_narration?: boolean; narration_mismatch?: boolean }>('/api/ai/script', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  aiTts: (payload: { text: string; shot_id?: string; voice?: string }) =>
    request<{ asset_id: string; url: string; duration: number; cached: boolean; slot: number; tempo: number; too_long: boolean }>('/api/ai/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  ttsSettings: () =>
    request<{ base_url: string; model: string; voice: string; proxy: string; key_set: boolean; key_hint: string; overridden: boolean; voices: Array<{ id: string; name: string }> }>(
      '/api/settings/tts',
    ),
  saveTtsSettings: (payload: { base_url: string; api_key?: string; model: string; voice: string; proxy?: string }) =>
    request<{ base_url: string; model: string; voice: string; key_set: boolean; key_hint: string; voices: Array<{ id: string; name: string }> }>(
      '/api/settings/tts',
      { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
    ),
  testTts: (payload: { base_url: string; api_key?: string; model: string; voice: string; proxy?: string }) =>
    request<{ ok: boolean; duration?: number; url?: string; error?: string }>('/api/settings/tts/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  shotFrames: (shotId: string, count: number) =>
    request<{ items: Array<{ url: string }> }>(`/api/shots/${shotId}/frames?count=${count}`),
  shotPreview: (shotId: string) =>
    request<{ url: string; duration: number; source: string; width: number; height: number }>(
      `/api/shots/${shotId}/preview`,
    ),
  renderTimeline: (renderId: string) =>
    request<{ items: Array<{ shot_id: string; title: string; duration: number; start: number; end: number }>; total: number }>(
      `/api/renders/${renderId}/timeline`,
    ),
  editState: (projectId: string) =>
    request<{ options: Record<string, unknown>; shot_edits: Array<Record<string, unknown>> }>(
      `/api/projects/${projectId}/edit-state`,
    ),
  saveEditState: (projectId: string, payload: { options: Record<string, unknown>; shot_edits: Array<Record<string, unknown>> }) =>
    request<{ ok: boolean }>(`/api/projects/${projectId}/edit-state`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  allRenders: (limit = 50, status?: string) =>
    request<{ items: Render[] }>(`/api/renders?limit=${limit}${status ? `&status=${status}` : ''}`),
  startRender: (id: string) => request<Render>(`/api/renders/${id}/start`, { method: 'POST' }),
  assets: (params: { kind?: string; q?: string; limit?: number; offset?: number } = {}) => {
    const qs = new URLSearchParams()
    if (params.kind) qs.set('kind', params.kind)
    if (params.q) qs.set('q', params.q)
    qs.set('limit', String(params.limit ?? 60))
    qs.set('offset', String(params.offset ?? 0))
    return request<{ items: Asset[]; total: number; limit: number; offset: number }>(`/api/assets?${qs.toString()}`)
  },
  assetUsage: (id: string) => request<AssetUsage>(`/api/assets/${id}/usage`),
  createShotFromAsset: (
    assetId: string,
    payload: { project_id: string; title?: string; mode: 'restore' | 'first_frame' | 'audio'; preset_id?: string },
  ) =>
    request<Shot>(`/api/assets/${assetId}/create-shot`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  cleanupTestAssets: () => request<{ ok: boolean; removed: number }>('/api/assets/cleanup-test', { method: 'POST' }),

  deleteAsset: (id: string) => request<{ ok: boolean }>(`/api/assets/${id}`, { method: 'DELETE' }),

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
  reorderShots: (projectId: string, shotIds: string[]) =>
    request<{ items: Shot[] }>(`/api/projects/${projectId}/shots/reorder`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ shot_ids: shotIds }),
    }),

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
  deleteJob: (jobId: string) => request<{ ok: boolean }>(`/api/jobs/${jobId}`, { method: 'DELETE' }),
  activateTake: (shotId: string, jobId: string) =>
    request<Shot>(`/api/shots/${shotId}/activate-take`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_id: jobId }),
    }),


  modelsCheck: (cardId?: string, source: 'live' | 'snapshot' = 'live') => {
    const params = new URLSearchParams({ source })
    if (cardId) params.set('card_id', cardId)
    return request<ModelCheckResult>(`/api/models/check?${params.toString()}`)
  },
  saveModelSource: (name: string, url: string, directory = '') =>
    request<{ ok: boolean; count: number }>('/api/models/sources', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, url, directory }),
    }),
  syncModelSources: () =>
    request<{ ok: boolean; files: number; before: number; after: number; updated: number }>('/api/models/sources/sync', { method: 'POST' }),
  modelsInventory: () => request<ModelInventory>('/api/models/inventory'),
  saveInventorySnapshot: () => request<{ ok: boolean; inventory: ModelInventory }>('/api/models/inventory/snapshot', { method: 'POST' }),
  inventorySnapshot: () => request<ModelInventory>('/api/models/inventory/snapshot'),

  ffmpegStatus: () => request<{ available: boolean; ffmpeg: string; ffprobe: string; hint: string; capabilities?: { subtitles?: boolean; xfade?: boolean } }>('/api/ffmpeg/status'),
  createRender: (
    projectId: string,
    shot_ids: string[],
    options: Record<string, unknown>,
    shot_edits: Array<Record<string, unknown>> = [],
  ) =>
    request<Render>(`/api/projects/${projectId}/renders`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ shot_ids, options, shot_edits }),
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
    const body = Array.isArray(value) ? value.map(String).filter(Boolean).join('\n') : typeof value === 'string' ? value : JSON.stringify(value)
    return key + ":\n" + body
  }).join('\n\n')
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
