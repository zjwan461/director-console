import { Fragment, useEffect, useRef, useState } from 'react'
import { api, formatBytes, rewriteStream } from '../api'
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
  const [assistKey, setAssistKey] = useState<string | null>(null)
  const [brief, setBrief] = useState('')
  const [assisting, setAssisting] = useState(false)
  const [assistError, setAssistError] = useState('')
  const [modes, setModes] = useState<PromptMode[]>([])
  const [aiConfigured, setAiConfigured] = useState(false)
  const [streamText, setStreamText] = useState('')
  const [assistDone, setAssistDone] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const assistField = card.fields.find((f) => f.key === assistKey) || null
  const assistRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    // 切能力卡时关掉助手，避免停在上一个卡的字段上
    setAssistKey(null)
    setAssistError('')
  }, [card.id])

  useEffect(() => {
    if (!assistField) return
    assistRef.current?.focus()
    assistRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [assistKey])

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

  const [pickerKey, setPickerKey] = useState<string | null>(null)
  const [pickerAssets, setPickerAssets] = useState<Asset[]>([])
  const [pickerLoading, setPickerLoading] = useState(false)

  const openPicker = async (key: string) => {
    setPickerKey(key)
    setPickerLoading(true)
    try {
      const res = await api.assets('image', 24)
      setPickerAssets(res.items)
    } catch {
      setPickerAssets([])
    } finally {
      setPickerLoading(false)
    }
  }

  const runAssist = async () => {
    if (!assistField) return
    if (!aiConfigured) {
      setAssistError('还没有配置提示词模型：在 config.yaml 设置 ai.api_key 后重试。')
      return
    }
    setAssisting(true)
    setAssistError('')
    setStreamText('')
    setAssistDone(false)
    const controller = new AbortController()
    abortRef.current = controller
    try {
      await rewriteStream(assistField.assist || 't2v', brief, {
        onDelta: (text) => setStreamText((prev) => prev + text),
        onDone: (content) => {
          setStreamText(content)
          onChange(assistField.key, content)
          setAssistDone(true)
        },
        onError: (message) => setAssistError(message),
      }, controller.signal)
    } catch (err) {
      if (!controller.signal.aborted) {
        setAssistError(err instanceof Error ? err.message : String(err))
      }
    } finally {
      setAssisting(false)
      abortRef.current = null
    }
  }

  const modeLabel = Object.fromEntries(modes.map((m) => [m.mode, m.label]))

  return (
    <div className="form">
      {card.fields.map((field) => {
        const open = assistKey === field.key && assistField
        return (
          <Fragment key={field.key}>
            <FieldRenderer
              field={field}
              value={values[field.key]}
              asset={assets[field.key]}
              onChange={(v) => onChange(field.key, v)}
              onUpload={(file) => void uploadField(field, file)}
              onAssist={field.assist ? () => { setAssistKey(field.key); setAssistError('') } : undefined}
              onPick={field.type === 'image' ? () => void openPicker(field.key) : undefined}
            />
            {pickerKey === field.key && (
              <div className="assist">
                <div className="row" style={{ justifyContent: 'space-between' }}>
                  <b>素材库（最近图片）</b>
                  <button className="ghost tiny" onClick={() => setPickerKey(null)}>关闭</button>
                </div>
                {pickerLoading && <div className="msg">加载中…</div>}
                {!pickerLoading && pickerAssets.length === 0 && (
                  <div className="msg">还没有图片素材，先用「剧照 / 角色图」生成一张。</div>
                )}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(96px, 1fr))', gap: 8 }}>
                  {pickerAssets.map((a) => (
                    <img
                      key={a.id}
                      src={a.url}
                      alt={a.id}
                      style={{ width: '100%', height: 96, objectFit: 'cover', borderRadius: 8, cursor: 'pointer' }}
                      onClick={() => {
                        setAssets((prev) => ({ ...prev, [field.key]: a }))
                        onChange(field.key, a.id)
                        setPickerKey(null)
                      }}
                    />
                  ))}
                </div>
              </div>
            )}
            {open && (
              <div className="assist">
                <b>提示词助手 · {modeLabel[assistField.assist || ''] || assistField.assist}</b>
                <small>
                  {aiConfigured
                    ? '用一句人话描述你想要的画面，模型会扩写成规范提示词。'
                    : '尚未配置提示词模型（config.yaml 的 ai.api_key）。填好内容后点生成会提示配置方法。'}
                </small>
                <textarea
                  ref={assistRef}
                  rows={5}
                  value={brief}
                  placeholder="例：雪夜，女侠推门走入寺庙，镜头跟拍，冷调，有旁白"
                  onChange={(e) => setBrief(e.target.value)}
                />
                {(assisting || streamText) && (
                  <pre className="logs" style={{ maxHeight: 220, whiteSpace: 'pre-wrap' }}>
                    {streamText || '正在生成…'}
                  </pre>
                )}
                {assistDone && <div className="notice">已填入下方描述框，可以继续修改。</div>}
                {assistError && <div className="notice err">{assistError}</div>}
                <div className="row">
                  <button
                    className="primary"
                    disabled={assisting || !brief.trim()}
                    onClick={() => void runAssist()}
                  >
                    {assisting ? <><span className="spin" /> 生成中</> : '生成提示词'}
                  </button>
                  <button
                    className="ghost"
                    onClick={() => {
                      if (assisting) abortRef.current?.abort()
                      setAssistKey(null)
                      setAssistError('')
                      setStreamText('')
                      setAssistDone(false)
                    }}
                  >
                    {assisting ? '停止' : '关闭'}
                  </button>
                </div>
              </div>
            )}
          </Fragment>
        )
      })}
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
  onPick?: () => void
}

function FieldRenderer({ field, value, asset, onChange, onUpload, onAssist, onPick }: FieldProps) {
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
        {field.type === 'image' && onPick && (
          <button className="ghost" style={{ alignSelf: 'flex-start', fontSize: 12 }} onClick={onPick}>
            从素材库选（生成过的图）
          </button>
        )}
      </div>
    )
  }

  if (field.type === 'size') {
    const size = (value as { aspect?: string; megapixels?: number }) || {}
    const presets = field.presets || []
    const mpLabel = (mp: number) => {
      if (mp >= 2) return '高分辨率'
      if (mp >= 1.5) return '显存要求高'
      if (mp >= 1) return '高画质'
      if (mp >= 0.7) return '清晰'
      if (mp >= 0.4) return '推荐'
      return '省显存草稿'
    }
    const MP_OPTIONS: Array<{ mp: number; label: string }> = (
      field.megapixels_options && field.megapixels_options.length
        ? field.megapixels_options
        : [0.2, 0.4, 0.7, 1.0, 1.5]
    ).map((mp) => ({ mp, label: mpLabel(mp) }))
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
