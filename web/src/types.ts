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
  workdir?: string
  advanced_panel?: string
  comfy_web?: string
  settings?: ComfySettings
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
  width?: number
  height?: number
  size?: number
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
  status: 'queued' | 'preparing' | 'rendering' | 'succeeded' | 'failed'
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
}
