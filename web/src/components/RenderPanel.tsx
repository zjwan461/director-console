import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, formatDuration, timeAgo } from '../api'
import type { Asset, Render, Shot } from '../types'

const RESOLUTIONS = [
  { key: '480p', label: '横屏 480p · 854×480', width: 854, height: 480, portrait: false },
  { key: '720p', label: '横屏 720p · 1280×720', width: 1280, height: 720, portrait: false },
  { key: '1080p', label: '横屏 1080p · 1920×1080', width: 1920, height: 1080, portrait: false },
  { key: '480p-v', label: '竖屏 480p · 480×854', width: 480, height: 854, portrait: true },
  { key: '720p-v', label: '竖屏 720p · 720×1280', width: 720, height: 1280, portrait: true },
  { key: '1080p-v', label: '竖屏 1080p · 1080×1920', width: 1080, height: 1920, portrait: true },
]

// 从镜头参数里猜项目画幅：镜头是 9:16 就用竖屏预设
function detectPortrait(shots: Shot[]): boolean {
  for (const shot of shots) {
    const values = (shot as unknown as { values?: Record<string, unknown> }).values || {}
    const size = values.size as { aspect?: string } | undefined
    const aspect = String(size?.aspect || '')
    if (aspect.includes('9:16') || aspect.includes('3:4') || aspect.includes('2:3')) return true
    if (aspect.includes('16:9') || aspect.includes('4:3')) return false
  }
  return false
}

interface Edit {
  in_point: string
  out_point: string
  subtitle: string
}

interface Props {
  projectId: string
  shots: Shot[]
}

export default function RenderPanel({ projectId, shots }: Props) {
  const [selected, setSelected] = useState<string[]>([])
  const [edits, setEdits] = useState<Record<string, Edit>>({})
  const [resKey, setResKey] = useState(() => (detectPortrait(shots) ? '720p-v' : '720p'))
  const [fps, setFps] = useState(24)
  const [audios, setAudios] = useState<Asset[]>([])
  const [bgmId, setBgmId] = useState('')
  const [bgmVolume, setBgmVolume] = useState(-14)
  const [fadeIn, setFadeIn] = useState(0.5)
  const [fadeOut, setFadeOut] = useState(0.5)
  const [loopBgm, setLoopBgm] = useState(true)
  const [subsEnabled, setSubsEnabled] = useState(true)
  const [subSize, setSubSize] = useState(42)
  const [subMargin, setSubMargin] = useState(48)
  const [loudness, setLoudness] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [active, setActive] = useState<Render | null>(null)
  const [draftNote, setDraftNote] = useState('')

  useEffect(() => {
    setResKey((prev) => {
      if (prev !== '720p' && prev !== '720p-v') return prev
      return detectPortrait(shots) ? '720p-v' : '720p'
    })
  }, [shots])
  const [caps, setCaps] = useState<{ subtitles?: boolean }>({})
  const timer = useRef<number | null>(null)

  useEffect(() => {
    api.assets({ kind: 'audio', limit: 50 }).then((res) => setAudios(res.items)).catch(() => undefined)
    api.ffmpegStatus()
      .then((s) => setCaps(((s as { capabilities?: { subtitles?: boolean } }).capabilities) || {}))
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    setSelected((prev) => {
      const keep = prev.filter((id) => shots.some((s) => s.id === id))
      return keep.length ? keep : shots.map((s) => s.id)
    })
  }, [shots])

  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current) }, [])

  const ordered = useMemo(() => shots.filter((s) => selected.includes(s.id)), [shots, selected])

  const toggle = (id: string) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))

  const editOf = (id: string): Edit => edits[id] || { in_point: '', out_point: '', subtitle: '' }
  const patchEdit = (id: string, patch: Partial<Edit>) =>
    setEdits((prev) => ({ ...prev, [id]: { ...editOf(id), ...patch } }))

  const poll = useCallback(async (id: string) => {
    try {
      const r = await api.render(id)
      setActive(r)
      if (r.status === 'succeeded' || r.status === 'failed') {
        setBusy(false)
        return
      }
      timer.current = window.setTimeout(() => void poll(id), 1500)
    } catch {
      setBusy(false)
    }
  }, [])

  const buildPayload = () => {
    const res = RESOLUTIONS.find((r) => r.key === resKey) || RESOLUTIONS[1]
    const shotEdits = ordered.map((s) => {
      const e = editOf(s.id)
      return {
        shot_id: s.id,
        in_point: Number(e.in_point) || 0,
        out_point: e.out_point ? Number(e.out_point) : undefined,
        subtitle: e.subtitle || s.title || '',
      }
    })
    return {
      width: res.width,
      height: res.height,
      shots: ordered.map((s) => s.id),
      shotEdits,
    }
  }

  const saveDraft = async () => {
    if (!ordered.length) return
    setError('')
    setDraftNote('')
    const { width, height, shots, shotEdits } = buildPayload()
    try {
      const render = await api.createRender(projectId, shots, {
        width, height, fps, draft: true,
        bgm: bgmId ? { asset_id: bgmId, volume_db: bgmVolume, fade_in: fadeIn, fade_out: fadeOut, loop: loopBgm } : {},
        subtitles: { enabled: subsEnabled, style: { size: subSize, margin_v: subMargin } },
        loudness: { enabled: loudness },
      }, shotEdits)
      setDraftNote(`已保存草稿 ${render.id}，可在「成片」页继续导出`)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const start = async () => {
    if (!ordered.length) return
    setBusy(true)
    setError('')
    const res = RESOLUTIONS.find((r) => r.key === resKey) || RESOLUTIONS[1]
    const shotEdits = ordered.map((s) => {
      const e = editOf(s.id)
      return {
        shot_id: s.id,
        in_point: Number(e.in_point) || 0,
        out_point: e.out_point ? Number(e.out_point) : undefined,
        subtitle: e.subtitle || s.title || '',
      }
    })
    try {
      const render = await api.createRender(projectId, ordered.map((s) => s.id), {
        width: res.width,
        height: res.height,
        fps,
        bgm: bgmId ? {
          asset_id: bgmId, volume_db: bgmVolume,
          fade_in: fadeIn, fade_out: fadeOut, loop: loopBgm,
        } : {},
        subtitles: { enabled: subsEnabled, style: { size: subSize, margin_v: subMargin } },
        loudness: { enabled: loudness },
      }, shotEdits)
      setActive(render)
      void poll(render.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setBusy(false)
    }
  }

  return (
    <>
      <div className="render-editor">
        <div className="panel">
          <h2>
            <span>镜头与字幕</span>
            <span className="meta">已选 {ordered.length} / {shots.length}</span>
          </h2>
          <p className="hint">勾选要导出的镜头；填「入点 / 出点」可剪掉首尾，字幕留空则用镜头标题。</p>
          <div className="list">
            {shots.map((shot) => {
              const on = selected.includes(shot.id)
              const edit = editOf(shot.id)
              return (
                <div key={shot.id} className={`render-shot ${on ? 'on' : ''}`}>
                  <div className="render-shot-head">
                    <input type="checkbox" checked={on} onChange={() => toggle(shot.id)} />
                    <b title={shot.title}>{shot.title || `镜头 ${shot.idx + 1}`}</b>
                    <span className="meta">{shot.last_frame_url ? '已出片' : '暂无产物'}</span>
                  </div>
                  {on && (
                    <div className="render-shot-edit">
                      <label>
                        入点
                        <input type="number" min={0} step={0.1} placeholder="0"
                               value={edit.in_point}
                               onChange={(e) => patchEdit(shot.id, { in_point: e.target.value })} />
                      </label>
                      <label>
                        出点
                        <input type="number" min={0} step={0.1} placeholder="到尾"
                               value={edit.out_point}
                               onChange={(e) => patchEdit(shot.id, { out_point: e.target.value })} />
                      </label>
                      <label className="grow">
                        字幕
                        <input placeholder={shot.title || '这一镜的字幕'}
                               value={edit.subtitle}
                               onChange={(e) => patchEdit(shot.id, { subtitle: e.target.value })} />
                      </label>
                    </div>
                  )}
                </div>
              )
            })}
            {!shots.length && <div className="empty">还没有镜头。</div>}
          </div>
        </div>

        <div className="panel">
          <h2>成片设置</h2>
          <div className="row">
            <select value={resKey} onChange={(e) => setResKey(e.target.value)}>
              {RESOLUTIONS.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
            </select>
            <select value={fps} onChange={(e) => setFps(Number(e.target.value))}>
              <option value={24}>24 fps</option>
              <option value={30}>30 fps</option>
            </select>
          </div>

          <h3>背景音乐</h3>
          <div className="row">
            <select className="grow" value={bgmId} onChange={(e) => setBgmId(e.target.value)}>
              <option value="">不加 BGM</option>
              {audios.map((a) => (
                <option key={a.id} value={a.id}>{a.path.split('/').pop()}</option>
              ))}
            </select>
          </div>
          {bgmId && (
            <>
              <label className="slider">
                音量 {bgmVolume} dB
                <input type="range" min={-30} max={0} step={1} value={bgmVolume}
                       onChange={(e) => setBgmVolume(Number(e.target.value))} />
              </label>
              <div className="row">
                <label className="slider grow">
                  淡入 {fadeIn}s
                  <input type="range" min={0} max={3} step={0.1} value={fadeIn}
                         onChange={(e) => setFadeIn(Number(e.target.value))} />
                </label>
                <label className="slider grow">
                  淡出 {fadeOut}s
                  <input type="range" min={0} max={3} step={0.1} value={fadeOut}
                         onChange={(e) => setFadeOut(Number(e.target.value))} />
                </label>
              </div>
              <label className="check">
                <input type="checkbox" checked={loopBgm} onChange={(e) => setLoopBgm(e.target.checked)} />
                循环铺满整个成片
              </label>
            </>
          )}

          <h3>字幕</h3>
          <label className="check">
            <input type="checkbox" checked={subsEnabled} onChange={(e) => setSubsEnabled(e.target.checked)} />
            烧录到画面
          </label>
          {subsEnabled && (
            <div className="row">
              <label className="slider grow">
                字号 {subSize}
                <input type="range" min={20} max={80} value={subSize}
                       onChange={(e) => setSubSize(Number(e.target.value))} />
              </label>
              <label className="slider grow">
                底部边距 {subMargin}
                <input type="range" min={0} max={160} value={subMargin}
                       onChange={(e) => setSubMargin(Number(e.target.value))} />
              </label>
            </div>
          )}
          {subsEnabled && caps.subtitles === false && (
            <div className="notice err" style={{ marginTop: 6 }}>
              当前 ffmpeg 不支持字幕烧录，只会导出 .srt 旁挂文件。
            </div>
          )}

          <h3>音频</h3>
          <label className="check">
            <input type="checkbox" checked={loudness} onChange={(e) => setLoudness(e.target.checked)} />
            响度标准化（-16 LUFS）
          </label>

          {error && <div className="notice err">{error}</div>}

          <div className="row-actions" style={{ marginTop: 12 }}>
            <button className="primary" disabled={busy || !ordered.length} onClick={() => void start()}>
              {busy ? <><span className="spin" /> 导出中</> : '导出成片'}
            </button>
            <button className="ghost" disabled={!ordered.length} onClick={() => void saveDraft()}>
              保存草稿
            </button>
            {active && <span className="meta">{active.message || active.status}</span>}
          </div>
          {draftNote && <div className="notice" style={{ marginTop: 8 }}>{draftNote}</div>}
          {active && (
            <div className="bar" style={{ marginTop: 8 }}>
              <i style={{ width: `${Math.round((active.progress || 0) * 100)}%` }} />
            </div>
          )}
        </div>
      </div>

      <div className="panel" style={{ marginTop: 14 }}>
        <h2>历史成片</h2>
        <RenderHistory projectId={projectId} />
      </div>
    </>
  )
}

export function RenderHistory({ projectId }: { projectId: string }) {
  const [items, setItems] = useState<Render[]>([])
  const load = useCallback(() => {
    api.renders(projectId).then((res) => setItems(res.items)).catch(() => undefined)
  }, [projectId])
  useEffect(() => {
    load()
    const t = window.setInterval(load, 4000)
    return () => window.clearInterval(t)
  }, [load])

  if (!items.length) return <div className="empty">还没有导出过成片。</div>
  return (
    <div className="list">
      {items.map((r) => (
        <div key={r.id} className="render-history-item">
          <span className={`badge ${r.status === 'failed' ? 'err' : r.status === 'succeeded' ? 'ok' : ''}`}>
            {r.status === 'succeeded' ? '完成' : r.status === 'failed' ? '失败' : '进行中'}
          </span>
          <span className="meta">{timeAgo(r.created_at)} · {r.shot_ids.length} 镜</span>
          {r.status === 'succeeded' && r.output_url && (
            <>
              <a href={r.output_url} download={r.download_name}>下载</a>
              <a href={r.output_url} target="_blank" rel="noreferrer">预览</a>
              <a href={`/api/renders/${r.id}/subtitles`}>字幕</a>
            </>
          )}
          {r.status === 'failed' && <span className="err">{r.error}</span>}
          {r.status !== 'succeeded' && r.status !== 'failed' && (
            <span className="meta">{r.message} · {formatDuration((Date.now() / 1000) - r.created_at)}</span>
          )}
        </div>
      ))}
    </div>
  )
}
