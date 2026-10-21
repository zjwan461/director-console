import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import type { Asset, Project, Shot } from '../types'

const RESOLUTIONS = [
  { key: '480p', label: '480p · 854×480', width: 854, height: 480 },
  { key: '720p', label: '720p · 1280×720', width: 1280, height: 720 },
  { key: '1080p', label: '1080p · 1920×1080', width: 1920, height: 1080 },
]

interface Edit {
  in_point: string
  out_point: string
  subtitle: string
}

export default function EditPanel({
  initialProjectId,
  onGoRenders,
}: {
  initialProjectId?: string
  onGoRenders: () => void
}) {
  const [projects, setProjects] = useState<Project[]>([])
  const [projectId, setProjectId] = useState(initialProjectId || '')
  const [shots, setShots] = useState<Shot[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [edits, setEdits] = useState<Record<string, Edit>>({})
  const [resKey, setResKey] = useState('720p')
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
  const [loaded, setLoaded] = useState(false)
  const [savedAt, setSavedAt] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const saveTimer = useRef<number | null>(null)

  useEffect(() => {
    api.projects().then((res) => {
      setProjects(res.items)
      if (!projectId && res.items.length) setProjectId(res.items[0].id)
    }).catch(() => undefined)
    api.assets({ kind: 'audio', limit: 50 }).then((res) => setAudios(res.items)).catch(() => undefined)
  }, [])

  // 载入项目 + 剪辑状态
  useEffect(() => {
    if (!projectId) return
    setLoaded(false)
    Promise.all([api.shots(projectId), api.editState(projectId)])
      .then(([shotRes, state]) => {
        setShots(shotRes.items)
        const opts = (state.options || {}) as Record<string, unknown>
        const w = Number(opts.width || 1280)
        setResKey(RESOLUTIONS.find((r) => r.width === w)?.key || '720p')
        setFps(Number(opts.fps || 24))
        const bgm = (opts.bgm || {}) as Record<string, unknown>
        setBgmId(String(bgm.asset_id || ''))
        setBgmVolume(Number(bgm.volume_db ?? -14))
        setFadeIn(Number(bgm.fade_in ?? 0.5))
        setFadeOut(Number(bgm.fade_out ?? 0.5))
        setLoopBgm(Boolean(bgm.loop ?? true))
        const subs = (opts.subtitles || {}) as Record<string, unknown>
        const style = (subs.style || {}) as Record<string, unknown>
        setSubsEnabled(Boolean(subs.enabled ?? true))
        setSubSize(Number(style.size || 42))
        setSubMargin(Number(style.margin_v || 48))
        setLoudness(Boolean((opts.loudness as Record<string, unknown>)?.enabled ?? true))

        const map: Record<string, Edit> = {}
        for (const item of state.shot_edits || []) {
          map[String(item.shot_id)] = {
            in_point: item.in_point ? String(item.in_point) : '',
            out_point: item.out_point ? String(item.out_point) : '',
            subtitle: String(item.subtitle || ''),
          }
        }
        setEdits(map)
        const savedIds = (state.shot_edits || []).map((e) => String(e.shot_id)).filter(Boolean)
        // 没有历史选择时默认全选，避免第一次进来「已选 0/1」导出不了
        setSelected(savedIds.length ? savedIds : shotRes.items.map((s) => s.id))
        setLoaded(true)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [projectId])

  useEffect(() => {
    if (!loaded || !projectId) return
    if (saveTimer.current) window.clearTimeout(saveTimer.current)
    saveTimer.current = window.setTimeout(() => {
      const res = RESOLUTIONS.find((r) => r.key === resKey) || RESOLUTIONS[1]
      api.saveEditState(projectId, {
        options: {
          width: res.width, height: res.height, fps,
          bgm: bgmId ? { asset_id: bgmId, volume_db: bgmVolume, fade_in: fadeIn, fade_out: fadeOut, loop: loopBgm } : {},
          subtitles: { enabled: subsEnabled, style: { size: subSize, margin_v: subMargin } },
          loudness: { enabled: loudness },
        },
        shot_edits: ordered.map((s) => ({
          shot_id: s.id,
          in_point: Number(editOf(s.id).in_point) || 0,
          out_point: editOf(s.id).out_point ? Number(editOf(s.id).out_point) : undefined,
          subtitle: editOf(s.id).subtitle || s.title || '',
        })),
      }).then(() => setSavedAt(new Date().toLocaleTimeString())).catch(() => undefined)
    }, 800)
  }, [loaded, projectId, resKey, fps, bgmId, bgmVolume, fadeIn, fadeOut, loopBgm,
      subsEnabled, subSize, subMargin, loudness, edits, selected, shots])

  const ordered = useMemo(() => shots.filter((s) => selected.includes(s.id)), [shots, selected])
  const editOf = (id: string): Edit => edits[id] || { in_point: '', out_point: '', subtitle: '' }
  const patchEdit = (id: string, patch: Partial<Edit>) =>
    setEdits((prev) => ({ ...prev, [id]: { ...editOf(id), ...patch } }))
  const toggle = (id: string) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))

  const exportRender = async () => {
    if (!ordered.length) return
    setBusy(true)
    setError('')
    const res = RESOLUTIONS.find((r) => r.key === resKey) || RESOLUTIONS[1]
    try {
      await api.createRender(projectId, ordered.map((s) => s.id), {
        width: res.width, height: res.height, fps,
        bgm: bgmId ? { asset_id: bgmId, volume_db: bgmVolume, fade_in: fadeIn, fade_out: fadeOut, loop: loopBgm } : {},
        subtitles: { enabled: subsEnabled, style: { size: subSize, margin_v: subMargin } },
        loudness: { enabled: loudness },
      }, ordered.map((s) => ({
        shot_id: s.id,
        in_point: Number(editOf(s.id).in_point) || 0,
        out_point: editOf(s.id).out_point ? Number(editOf(s.id).out_point) : undefined,
        subtitle: editOf(s.id).subtitle || s.title || '',
      })))
      onGoRenders()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>剪辑</h1>
          <p>选镜头、剪首尾、写字幕、配 BGM；改动自动保存，下次回来接着改。</p>
        </div>
        <div className="row">
          <select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          {savedAt && <span className="meta">已自动保存 {savedAt}</span>}
        </div>
      </div>

      {error && <div className="notice err">{error}</div>}

      <div className="render-editor">
        <div className="panel">
          <h2>
            <span>镜头与字幕</span>
            <span className="meta">已选 {ordered.length} / {shots.length}</span>
          </h2>
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
            {!shots.length && <div className="empty">这个项目还没有镜头，先去项目页加一镜。</div>}
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

          <h3>音频</h3>
          <label className="check">
            <input type="checkbox" checked={loudness} onChange={(e) => setLoudness(e.target.checked)} />
            响度标准化（-16 LUFS）
          </label>

          <div className="row-actions" style={{ marginTop: 12 }}>
            <button className="primary" disabled={busy || !ordered.length} onClick={() => void exportRender()}>
              {busy ? '提交中…' : '导出成片'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
