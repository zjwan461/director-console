import { useEffect, useRef, useState } from 'react'
import { api, formatBytes } from '../api'
import type { Asset, Preset, PresetField, PromptMode } from '../types'

export function makeDefaults(card: Preset): Record<string, unknown> {
  const values: Record<string, unknown> = {}
  for (const field of card.fields) {
    if (field.type === 'size') {
      values[field.key] = {
        aspect: field.default_aspect ?? '16:9',
        megapixels: field.default_megapixels ?? 0.4,
      }
    } else if (field.type === 'duration') {
      values[field.key] = field.default ?? 5
    } else if (field.type === 'seed') {
      values[field.key] = -1
    } else if (field.type === 'image' || field.type === 'video' || field.type === 'audio') {
      values[field.key] = ''
    } else {
      values[field.key] = field.default ?? ''
    }
  }
  return values
}

interface Props {
  card: Preset
  values: Record<string, unknown>
  onChange: (key: string, value: unknown) => void
  assets: Record<string, Asset>
  setAssets: (updater: (prev: Record<string, Asset>) => Record<string, Asset>) => void
  onError: (message: string) => void
}

export default function PresetFields({ card, values, onChange, assets, setAssets, onError }: Props) {
  const [assistField, setAssistField] = useState<PresetField | null>(null)
  const [brief, setBrief] = useState('')
  const [assisting, setAssisting] = useState(false)
  const [assistError, setAssistError] = useState('')
  const [modes, setModes] = useState<PromptMode[]>([])
  const [aiConfigured, setAiConfigured] = useState(false)

  useEffect(() => {
    api.promptModes().then((res) => {
      setModes(res.items)
      setAiConfigured(res.ai_configured)
    }).catch(() => undefined)
  }, [])

  const uploadField = async (field: PresetField, file: File) => {
    try {
      const kind = field.type === 'image' ? 'image' : field.type === 'audio' ? 'audio' : 'video'
      const asset = await api.upload(file, kind)
      setAssets((prev) => ({ ...prev, [field.key]: asset }))
      onChange(field.key, asset.id)
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err))
    }
  }

  const runAssist = async () => {
    if (!assistField) return
    setAssisting(true)
    setAssistError('')
    try {
      const res = await api.rewrite(assistField.assist || 't2v', brief)
      onChange(assistField.key, res.content)
      setAssistField(null)
      setBrief('')
    } catch (err) {
      setAssistError(err instanceof Error ? err.message : String(err))
    } finally {
      setAssisting(false)
    }
  }

  const modeLabel = Object.fromEntries(modes.map((m) => [m.mode, m.label]))

  return (
    <div className="form">
      {card.fields.map((field) => (
        <FieldRenderer
          key={field.key}
          field={field}
          value={values[field.key]}
          asset={assets[field.key]}
          onChange={(v) => onChange(field.key, v)}
          onUpload={(file) => void uploadField(field, file)}
          onAssist={field.assist ? () => { setAssistField(field); setAssistError('') } : undefined}
        />
      ))}

      {assistField && (
        <div className="assist">
          <b>提示词助手 · {modeLabel[assistField.assist || ''] || assistField.assist}</b>
          <small>
            {aiConfigured
              ? '用一句人话描述你想要的画面，模型会扩写成 H3 规范格式。'
              : '尚未配置提示词模型（config.yaml 的 ai.api_key），配置后才能一键扩写。'}
          </small>
          <textarea
            rows={5}
            value={brief}
            placeholder="例：雪夜，女侠推门走入寺庙，镜头跟拍，冷调，有旁白"
            onChange={(e) => setBrief(e.target.value)}
          />
          {assistError && <div className="notice err">{assistError}</div>}
          <div className="row">
            <button className="primary" disabled={!aiConfigured || assisting || !brief.trim()} onClick={() => void runAssist()}>
              {assisting ? <><span className="spin" /> 生成中</> : '生成提示词'}
            </button>
            <button className="ghost" onClick={() => setAssistField(null)}>取消</button>
          </div>
        </div>
      )}
    </div>
  )
}

interface FieldProps {
  field: PresetField
  value: unknown
  asset?: Asset
  onChange: (value: unknown) => void
  onUpload: (file: File) => void
  onAssist?: () => void
}

function FieldRenderer({ field, value, asset, onChange, onUpload, onAssist }: FieldProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  if (field.type === 'textarea') {
    return (
      <div className="field">
        <label>
          <span>{field.label} {field.required && <span className="req">*</span>}</span>
          {onAssist && <button className="ghost" style={{ padding: '3px 8px', fontSize: 11 }} onClick={onAssist}>提示词助手</button>}
        </label>
        <textarea
          rows={field.rows || 6}
          value={String(value ?? '')}
          placeholder={field.placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
        {field.placeholder && <span className="helper">{field.placeholder}</span>}
      </div>
    )
  }

  if (field.type === 'image' || field.type === 'video' || field.type === 'audio') {
    const accept = field.type === 'image' ? 'image/*' : field.type === 'audio' ? 'audio/*' : 'video/*'
    return (
      <div className="field">
        <label><span>{field.label} {field.required && <span className="req">*</span>}</span></label>
        <div className="dropzone" onClick={() => inputRef.current?.click()}>
          {asset && field.type === 'image'
            ? <img className="thumb" src={asset.url} alt={field.label} />
            : <div className="thumb">{asset ? (field.type === 'audio' ? '音频' : '视频') : '＋'}</div>}
          <div>
            <div>{asset ? asset.path.split('/').pop() : '点击选择文件'}</div>
            <small>{asset ? `${asset.width || 0}×${asset.height || 0} · ${formatBytes(asset.size)}` : '点击选择，单个文件建议 ≤ 50MB'}</small>
          </div>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) onUpload(file)
            e.target.value = ''
          }}
        />
      </div>
    )
  }

  if (field.type === 'size') {
    const size = (value as { aspect?: string; megapixels?: number }) || {}
    const presets = field.presets || []
    const MP_OPTIONS: Array<{ mp: number; label: string }> = [
      { mp: 0.2, label: '省显存草稿' },
      { mp: 0.4, label: '推荐' },
      { mp: 0.7, label: '清晰' },
      { mp: 1.0, label: '高画质' },
      { mp: 1.5, label: '显存要求高' },
    ]
    const current = Number(size.megapixels ?? 0.4)
    // 工作流默认值可能不在预设里（比如 1.2 / 0.9），补一条“自定义”避免选择框回落到第一项
    const options = MP_OPTIONS.some((o) => Math.abs(o.mp - current) < 1e-6)
      ? MP_OPTIONS
      : [...MP_OPTIONS, { mp: current, label: '自定义' }].sort((a, b) => a.mp - b.mp)
    return (
      <div className="field">
        <label><span>{field.label}</span><span className="meta">{size.aspect} · {current} MP</span></label>
        <div className="chips">
          {presets.map((preset) => (
            <button
              key={preset.aspect}
              className={`chip ${size.aspect === preset.aspect ? 'active' : ''}`}
              onClick={() => onChange({ ...size, aspect: preset.aspect, megapixels: preset.megapixels })}
            >
              {preset.label}
            </button>
          ))}
          {presets.length === 0 && <span className="meta">使用工作流默认画幅</span>}
        </div>
        <div className="row">
          <select
            className="grow"
            value={String(current)}
            onChange={(e) => onChange({ ...size, megapixels: Number(e.target.value) })}
          >
            {options.map((opt) => (
              <option key={opt.mp} value={String(opt.mp)}>
                {opt.mp.toFixed(1)} MP · {opt.label}
              </option>
            ))}
          </select>
        </div>
      </div>
    )
  }

  if (field.type === 'duration') {
    const seconds = Number(value ?? field.default ?? 5)
    return (
      <div className="field">
        <label>
          <span>{field.label}</span>
          <span className="meta">约 {seconds} 秒 · 约 {field.frame_hint ?? Math.round(seconds * 24)} 帧</span>
        </label>
        <div className="row">
          <input
            type="range"
            className="grow"
            min={field.min ?? 1}
            max={field.max ?? 15}
            step={1}
            value={seconds}
            onChange={(e) => onChange(Number(e.target.value))}
          />
          <input
            type="number"
            style={{ width: 90 }}
            min={field.min ?? 1}
            max={field.max ?? 15}
            value={seconds}
            onChange={(e) => onChange(Number(e.target.value))}
          />
        </div>
        <span className="helper">H3 会按 24fps 的 4n+1 帧网格向上取整，实际时长会略长一点。</span>
      </div>
    )
  }

  if (field.type === 'seed') {
    return (
      <div className="field">
        <label><span>{field.label}</span><span className="meta">-1 = 每次随机</span></label>
        <input type="number" value={Number(value ?? -1)} onChange={(e) => onChange(Number(e.target.value))} />
      </div>
    )
  }

  if (field.type === 'select') {
    return (
      <div className="field">
        <label><span>{field.label}</span></label>
        <select value={String(value ?? '')} onChange={(e) => onChange(e.target.value)}>
          {(field.options || []).map((opt) => <option key={opt} value={opt}>{opt}</option>)}
        </select>
      </div>
    )
  }

  return (
    <div className="field">
      <label><span>{field.label} {field.required && <span className="req">*</span>}</span></label>
      <input
        type={field.type === 'number' ? 'number' : 'text'}
        value={String(value ?? '')}
        onChange={(e) => onChange(field.type === 'number' ? Number(e.target.value) : e.target.value)}
      />
    </div>
  )
}
