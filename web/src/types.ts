export type FieldType =
  | 'text'
  | 'textarea'
  | 'image'
  | 'video'
  | 'audio'
  | 'size'
  | 'duration'
  | 'seed'
  | 'number'
  | 'select'

export interface SizePreset {
  aspect: string
  megapixels: number
  label: string
}

export interface PresetField {
  key: string
  type: FieldType
  label: string
  required?: boolean
  rows?: number
  placeholder?: string
  assist?: string
  default?: unknown
  min?: number
  max?: number
  frame_hint?: number
  mode?: 'wh' | 'aspect_mp'
  presets?: SizePreset[]
  default_aspect?: string
  default_megapixels?: number
  options?: string[]
  megapixels_options?: number[]
}

export interface Preset {
  id: string
  name: string
  badge?: string
  desc?: string
  hint?: string
  category?: string
  output_kind?: string
  fields: PresetField[]
  error?: string
}

export interface Output {
  kind: string
  name: string
  url: string
  size?: number
  error?: string
  text?: string
  node?: string
}

export interface Job {
  id: string
  preset_id: string
  project_id?: string
  shot_id?: string
  status: 'queued' | 'uploading' | 'running' | 'succeeded' | 'failed' | 'canceled'
  progress: number
  message?: string
  error?: string
  outputs: Output[]
  inputs: Record<string, unknown>
  created_at: number
  finished_at?: number
}

export interface JobsPage {
  items: Job[]
  has_more: boolean
  next_cursor: string | null
}

export interface ComfySettings {
  mode: string
  base_url: string
  token_set: boolean
  token_hint: string
  managed: boolean
  overridden: boolean
}

export interface ServiceStatus {
  mode: string
  managed: boolean
  base_url: string
  running: boolean
  managed_pid?: number | null
  managed_uptime?: number
  managed_adopted?: boolean
  workdir?: string
  advanced_panel?: string
  comfy_web?: string
  settings?: ComfySettings
  local?: {
    url: string
    running: boolean
    health?: {
      ok?: boolean
      latency_ms?: number
      error?: string
      system?: Record<string, unknown>
      devices?: Array<{ name?: string; vram_total?: number; vram_free?: number }>
    }
  }
  health?: {
    ok?: boolean
    mock?: boolean
    latency_ms?: number
    error?: string
    system?: Record<string, unknown>
    devices?: Array<{ name?: string; vram_total?: number; vram_free?: number }>
  }
}

export interface Asset {
  id: string
  kind: string
  path: string
  url: string
  meta?: Record<string, unknown>
  width?: number
  height?: number
  size?: number
  created_at?: number
  purpose?: string
}

export interface PromptMode {
  mode: string
  label: string
  desc: string
  available: boolean
}

export interface Project {
  id: string
  name: string
  style?: string
  notes?: string
  created_at: number
  shots?: number
}

export interface Shot {
  active_job?: string
  id: string
  project_id: string
  idx: number
  title: string
  preset_id: string
  prompt?: string
  cover?: string
  last_frame?: string
  last_frame_url?: string
  last_frame_ambiguous?: boolean
  values?: Record<string, unknown>
  created_at: number
}

export interface Render {
  id: string
  project_id: string
  project_name?: string
  status: 'draft' | 'queued' | 'preparing' | 'rendering' | 'succeeded' | 'failed' | 'canceled'
  progress: number
  message?: string
  shot_ids: string[]
  options?: Record<string, unknown>
  output_url?: string
  cover_url?: string
  download_name?: string
  error?: string
  created_at: number
  finished_at?: number
  duration?: number
  size_bytes?: number
  is_preview?: boolean
  summary?: {
    preview: boolean
    width: number
    height: number
    fps: number
    transition: string
    bgm: boolean
    subtitles: boolean
    loudness: boolean
    title: string
    tail: string
  }
}

export interface ModelRef {
  file: string
  category: string
  field: string
  node: string
  exists: boolean
  command: string
  search_url: string
  url?: string
  source?: string
  search?: { huggingface?: string; modelscope?: string; civitai?: string }
  reason?: string
  class_type?: string
}

export interface ModelCheckCard {
  id: string
  name: string
  models: ModelRef[]
  total: number
  missing_count: number
}

export interface ModelCheckResult {
  cards: ModelCheckCard[]
  summary: { cards: number; models: number; missing: number }
  comfy: { base_url: string }
}

export interface ModelInventory {
  base_url: string
  fetched_at: number
  source: string
  file_count: number
  folders: Record<string, string[]>
  files: string[]
}

export interface AssetUsageShot {
  project_id: string
  project_name: string
  shot_id: string
  shot_title: string
  fields: string[]
}

export interface AssetUsageJob {
  id: string
  preset_id: string
  status: string
  created_at: number
}

export interface AssetUsage {
  asset: Asset
  shots: AssetUsageShot[]
  jobs: AssetUsageJob[]
}


/* ---------------- 导演助手 ---------------- */
export interface AgentThread {
  id: string
  title: string
  project_id: string
  created_at: number
  updated_at: number
  preview?: string
}

export interface AgentPart {
  type: string
  [key: string]: unknown
}

export interface AgentMessage {
  id: string
  thread_id: string
  run_id?: string
  role: 'user' | 'assistant' | 'tool' | 'system'
  content: string
  parts: AgentPart[]
  seq: number
  created_at: number
}

export interface AgentRun {
  id: string
  thread_id: string
  status: 'running' | 'waiting_confirm' | 'done' | 'failed' | 'canceled' | 'interrupted'
  node: string
  pending: Record<string, unknown>
  error: string
  steps: number
  started_at: number
  finished_at?: number | null
}

export interface AgentArtifact {
  id: string
  kind: string
  ref_id: string
  url: string
  meta: Record<string, unknown>
  created_at: number
}

export interface AgentEvent {
  seq: number
  ts: number
  t: string
  [key: string]: unknown
}
