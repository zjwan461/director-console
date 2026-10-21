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
  voice_asset: string
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
  const [images, setImages] = useState<Asset[]>([])
  const [titleOn, setTitleOn] = useState(false)
  const [titleText, setTitleText] = useState('')
  const [titleDur, setTitleDur] = useState(1.5)
  const [titleBg, setTitleBg] = useState('#000000')
  const [titleImage, setTitleImage] = useState('')
  const [tailOn, setTailOn] = useState(false)
  const [tailText, setTailText] = useState('')
  const [tailDur, setTailDur] = useState(2)
  const [tailBg, setTailBg] = useState('#000000')
  const [tailImage, setTailImage] = useState('')
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
  const [activeShot, setActiveShot] = useState('')
  const [uploadFor, setUploadFor] = useState('')
  const voiceInput = useRef<HTMLInputElement | null>(null)
  const [shotPreview, setShotPreview] = useState<{ url: string; duration: number }>({ url: '', duration: 0 })
  const [previewJob, setPreviewJob] = useState<{ id: string; status: string; message: string; url?: string } | null>(null)
  const [timeline, setTimeline] = useState<Array<{ shot_id: string; title: string; duration: number; start: number; end: number }>>([])
  const [transType, setTransType] = useState('none')
  const [transDur, setTransDur] = useState(0.4)
  const saveTimer = useRef<number | null>(null)
  const pollTimer = useRef<number | null>(null)

  useEffect(() => {
    api.projects().then((res) => {
      setProjects(res.items)
      if (!projectId && res.items.length) setProjectId(res.items[0].id)
    }).catch(() => undefined)
    api.assets({ kind: 'audio', limit: 50 }).then((res) => setAudios(res.items)).catch(() => undefined)
    api.assets({ kind: 'image', limit: 50 }).then((res) => setImages(res.items)).catch(() => undefined)
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
        const title = (opts.title || {}) as Record<string, unknown>
        setTitleOn(Boolean(title.enabled))
        setTitleText(String(title.text || ''))
        setTitleDur(Number(title.duration ?? 1.5))
        setTitleBg(String(title.bg || '#000000'))
        setTitleImage(String(title.bg_asset || ''))
        const tail = (opts.tail || {}) as Record<string, unknown>
        setTailOn(Boolean(tail.enabled))
        setTailText(String(tail.text || ''))
        setTailDur(Number(tail.duration ?? 2))
        setTailBg(String(tail.bg || '#000000'))
        setTailImage(String(tail.bg_asset || ''))
        const trans = (opts.transition || {}) as Record<string, unknown>
        setTransType(String(trans.type || 'none'))
        setTransDur(Number(trans.duration ?? 0.4))
        setActiveShot(shotRes.items[0]?.id || '')

        const map: Record<string, Edit> = {}
        for (const item of state.shot_edits || []) {
          map[String(item.shot_id)] = {
            in_point: item.in_point ? String(item.in_point) : '',
            out_point: item.out_point ? String(item.out_point) : '',
            subtitle: String(item.subtitle || ''),
            voice_asset: String(item.voice_asset || ''),
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
          transition: { type: transType, duration: transDur },
          title: { enabled: titleOn, text: titleText, duration: titleDur, bg: titleBg, bg_asset: titleImage },
          tail: { enabled: tailOn, text: tailText, duration: tailDur, bg: tailBg, bg_asset: tailImage },
          bgm: bgmId ? { asset_id: bgmId, volume_db: bgmVolume, fade_in: fadeIn, fade_out: fadeOut, loop: loopBgm } : {},
          subtitles: { enabled: subsEnabled, style: { size: subSize, margin_v: subMargin } },
          loudness: { enabled: loudness },
        },
        shot_edits: ordered.map((s) => ({
          shot_id: s.id,
          in_point: Number(editOf(s.id).in_point) || 0,
          out_point: editOf(s.id).out_point ? Number(editOf(s.id).out_point) : undefined,
          subtitle: editOf(s.id).subtitle || s.title || '',
          voice_asset: editOf(s.id).voice_asset || '',
        })),
      }).then(() => setSavedAt(new Date().toLocaleTimeString())).catch(() => undefined)
    }, 800)
  }, [loaded, projectId, resKey, fps, bgmId, bgmVolume, fadeIn, fadeOut, loopBgm,
      subsEnabled, subSize, subMargin, loudness, transType, transDur, titleOn, titleText, titleDur, titleBg, titleImage,
      tailOn, tailText, tailDur, tailBg, tailImage, edits, selected, shots])

  useEffect(() => {
    if (!activeShot) return
    api.shotPreview(activeShot)
      .then((res) => setShotPreview({ url: res.url, duration: res.duration }))
      .catch(() => setShotPreview({ url: '', duration: 0 }))
  }, [activeShot])

  useEffect(() => () => {
    if (pollTimer.current) window.clearTimeout(pollTimer.current)
  }, [])

  useEffect(() => {
    let cancelled = false
    if (!ordered.length) { setTimeline([]); return }
    const overlap = transType === 'none' ? 0 : transDur
    Promise.all(ordered.map((s) => api.shotPreview(s.id).catch(() => ({ duration: 0 })))).then((list) => {
      if (cancelled) return
      let cursor = 0
      const items = ordered.map((s, i) => {
        const edit = editOf(s.id)
        const total = Number(list[i].duration) || 0
        const startAt = Number(edit.in_point) || 0
        const endAt = edit.out_point ? Math.min(Number(edit.out_point), total || Number(edit.out_point)) : total
        const dur = Math.max(0, endAt - startAt)
        if (i && overlap) cursor = Math.max(0, cursor - overlap)
        const item = { shot_id: s.id, title: s.title || `镜头 ${i + 1}`, duration: dur, start: cursor, end: cursor + dur }
        cursor += dur
        return item
      })
      setTimeline(items)
    })
    return () => { cancelled = true }
  }, [selected, shots, edits, transType, transDur])

  const ordered = useMemo(() => shots.filter((s) => selected.includes(s.id)), [shots, selected])
  const editOf = (id: string): Edit => edits[id] || { in_point: '', out_point: '', subtitle: '', voice_asset: '' }
  const patchEdit = (id: string, patch: Partial<Edit>) =>
    setEdits((prev) => ({ ...prev, [id]: { ...editOf(id), ...patch } }))
  const uploadVoice = async (files: FileList | null) => {
    if (!files || !files.length || !uploadFor) return
    try {
      const asset = await api.upload(files[0], 'audio')
      patchEdit(uploadFor, { voice_asset: asset.id })
      const res = await api.assets({ kind: 'audio', limit: 50 })
      setAudios(res.items)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setUploadFor('')
      if (voiceInput.current) voiceInput.current.value = ''
    }
  }

  const toggle = (id: string) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))

  const startPreview = async () => {
    if (!ordered.length) return
    setBusy(true)
    setError('')
    setPreviewJob(null)
    const res = RESOLUTIONS.find((r) => r.key === resKey) || RESOLUTIONS[1]
    try {
      const render = await api.createRender(projectId, ordered.map((s) => s.id), {
        width: res.width, height: res.height, fps, preview: true,
        transition: { type: transType, duration: transDur },
        title: { enabled: titleOn, text: titleText, duration: titleDur, bg: titleBg, bg_asset: titleImage },
        tail: { enabled: tailOn, text: tailText, duration: tailDur, bg: tailBg, bg_asset: tailImage },
      }, ordered.map((s) => ({
        shot_id: s.id,
        in_point: Number(editOf(s.id).in_point) || 0,
        out_point: editOf(s.id).out_point ? Number(editOf(s.id).out_point) : undefined,
        subtitle: editOf(s.id).subtitle || s.title || '',
        voice_asset: editOf(s.id).voice_asset || '',
      })))
      setPreviewJob({ id: render.id, status: render.status, message: render.message || '排队中' })
      const poll = async (id: string) => {
        const r = await api.render(id)
        setPreviewJob({ id: r.id, status: r.status, message: r.message || '', url: r.output_url })
        if (r.status === 'succeeded' || r.status === 'failed') {
          if (r.status === 'failed') setError(r.error || '预览失败')
          return
        }
        pollTimer.current = window.setTimeout(() => void poll(id), 2000)
      }
      void poll(render.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const exportRender = async () => {
    if (!ordered.length) return
    setBusy(true)
    setError('')
    const res = RESOLUTIONS.find((r) => r.key === resKey) || RESOLUTIONS[1]
    try {
      await api.createRender(projectId, ordered.map((s) => s.id), {
        width: res.width, height: res.height, fps,
        transition: { type: transType, duration: transDur },
        title: { enabled: titleOn, text: titleText, duration: titleDur, bg: titleBg, bg_asset: titleImage },
        tail: { enabled: tailOn, text: tailText, duration: tailDur, bg: tailBg, bg_asset: tailImage },
        bgm: bgmId ? { asset_id: bgmId, volume_db: bgmVolume, fade_in: fadeIn, fade_out: fadeOut, loop: loopBgm } : {},
        subtitles: { enabled: subsEnabled, style: { size: subSize, margin_v: subMargin } },
        loudness: { enabled: loudness },
      }, ordered.map((s) => ({
        shot_id: s.id,
        in_point: Number(editOf(s.id).in_point) || 0,
        out_point: editOf(s.id).out_point ? Number(editOf(s.id).out_point) : undefined,
        subtitle: editOf(s.id).subtitle || s.title || '',
        voice_asset: editOf(s.id).voice_asset || '',
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

      <input ref={voiceInput} type="file" hidden accept="audio/*"
             onChange={(e) => void uploadVoice(e.target.files)} />
      {error && <div className="notice err">{error}</div>}

      <div className="render-editor">
        <div className="panel">
          <h2>
            <span>镜头与字幕</span>
            <span className="meta">
              已选 {ordered.length} / {shots.length}
              {timeline.length
                ? ` · 总时长 ${(
                    timeline[timeline.length - 1].end +
                    (titleOn && titleText.trim() ? titleDur : 0) +
                    (tailOn && tailText.trim() ? tailDur : 0)
                  ).toFixed(1)}s`
                : ''}
            </span>
          </h2>

          <div className="timeline">
            {timeline.map((item) => (
              <button key={item.shot_id}
                      className={`timeline-seg ${activeShot === item.shot_id ? 'on' : ''}`}
                      style={{ flexGrow: Math.max(item.duration, 0.4) }}
                      title={`${item.title} · ${item.duration.toFixed(1)}s`}
                      onClick={() => setActiveShot(item.shot_id)}>
                <span>{item.title}</span>
                <i>{item.duration.toFixed(1)}s</i>
              </button>
            ))}
            {!timeline.length && <div className="empty">勾选镜头后这里显示时间轴</div>}
          </div>

          <div className="list">
            {shots.map((shot) => {
              const on = selected.includes(shot.id)
              const edit = editOf(shot.id)
              return (
                <div key={shot.id} className={`render-shot ${on ? 'on' : ''} ${activeShot === shot.id ? 'active' : ''}`}
                     onClick={() => setActiveShot(shot.id)}>
                  <div className="render-shot-head">
                    <input type="checkbox" checked={on} onChange={() => toggle(shot.id)}
                           onClick={(e) => e.stopPropagation()} />
                    <b title={shot.title}>{shot.title || `镜头 ${shot.idx + 1}`}</b>
                    <span className="meta">{shot.last_frame_url ? '已出片' : '暂无产物'}</span>
                  </div>
                  {on && (
                    <div className="render-shot-edit" onClick={(e) => e.stopPropagation()}>
                      <div className="shot-row">
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
                      <div className="shot-row">
                        <label className="grow">
                          旁白
                          <div className="voice-pick">
                            <select className="grow" value={edit.voice_asset}
                                    onChange={(e) => patchEdit(shot.id, { voice_asset: e.target.value })}>
                              <option value="">无旁白</option>
                              {audios.map((a) => (
                                <option key={a.id} value={a.id}>{a.path.split('/').pop()}</option>
                              ))}
                            </select>
                            <button className="ghost tiny"
                                    onClick={() => { setUploadFor(shot.id); voiceInput.current?.click() }}>
                              上传
                            </button>
                          </div>
                        </label>
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
            {!shots.length && <div className="empty">这个项目还没有镜头，先去项目页加一镜。</div>}
          </div>
        </div>

        <div className="panel">
          <h2>
            <span>预览</span>
            <span className="meta">{activeShot ? (shots.find((s) => s.id === activeShot)?.title || '') : '选择镜头'}</span>
          </h2>
          {(previewJob?.status === 'succeeded' && previewJob.url) || shotPreview.url ? (
            <video key={previewJob?.url || shotPreview.url} className="preview-video"
                   src={previewJob?.status === 'succeeded' && previewJob.url ? previewJob.url : shotPreview.url} controls />
          ) : (
            <div className="preview-empty">这个镜头还没有可预览的视频</div>
          )}
          {previewJob && !['succeeded', 'failed'].includes(previewJob.status) && (
            <div className="notice" style={{ marginTop: 8 }}>整片预览：{previewJob.message || previewJob.status}</div>
          )}

          <div className="trim">
            <div className="trim-head">
              <span>入点 {Math.min(Number(editOf(activeShot).in_point) || 0, shotPreview.duration || 0).toFixed(2)}s</span>
              <span>出点 {(editOf(activeShot).out_point ? Math.min(Number(editOf(activeShot).out_point), shotPreview.duration || 0) : shotPreview.duration).toFixed(2)}s</span>
            </div>
            <input type="range" min={0} max={shotPreview.duration || 1} step={0.05}
                   disabled={!shotPreview.duration || !activeShot}
                   value={Math.min(Number(editOf(activeShot).in_point) || 0, shotPreview.duration || 0)}
                   onChange={(e) => patchEdit(activeShot, { in_point: e.target.value })} />
            <input type="range" min={0} max={shotPreview.duration || 1} step={0.05}
                   disabled={!shotPreview.duration || !activeShot}
                   value={editOf(activeShot).out_point ? Math.min(Number(editOf(activeShot).out_point), shotPreview.duration) : shotPreview.duration}
                   onChange={(e) => patchEdit(activeShot, { out_point: e.target.value })} />
          </div>

          <h2 style={{ marginTop: 14 }}>成片设置</h2>
          <div className="row">
            <select value={resKey} onChange={(e) => setResKey(e.target.value)}>
              {RESOLUTIONS.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
            </select>
            <select value={fps} onChange={(e) => setFps(Number(e.target.value))}>
              <option value={24}>24 fps</option>
              <option value={30}>30 fps</option>
            </select>
          </div>

          <h3>转场</h3>
          <div className="row">
            <select className="grow" value={transType} onChange={(e) => setTransType(e.target.value)}>
              <option value="none">不加转场（直接切）</option>
              <option value="fade">淡入淡出</option>
              <option value="dissolve">交叉溶解</option>
            </select>
            {transType !== 'none' && (
              <select value={transDur} onChange={(e) => setTransDur(Number(e.target.value))}>
                <option value={0.2}>0.2s</option>
                <option value={0.3}>0.3s</option>
                <option value={0.4}>0.4s</option>
                <option value={0.5}>0.5s</option>
                <option value={0.8}>0.8s</option>
              </select>
            )}
          </div>

          <h3>片头片尾</h3>
          <label className="check">
            <input type="checkbox" checked={titleOn} onChange={(e) => setTitleOn(e.target.checked)} />
            片头
          </label>
          {titleOn && (
            <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>
              <input className="grow" placeholder="片头文字，如：雪夜"
                     value={titleText} onChange={(e) => setTitleText(e.target.value)} />
              <select value={titleDur} onChange={(e) => setTitleDur(Number(e.target.value))}>
                <option value={1}>1s</option>
                <option value={1.5}>1.5s</option>
                <option value={2}>2s</option>
                <option value={3}>3s</option>
              </select>
              <input type="color" value={titleBg} onChange={(e) => setTitleBg(e.target.value)} />
              <select value={titleImage} onChange={(e) => setTitleImage(e.target.value)}>
                <option value="">纯色背景</option>
                {images.map((a) => <option key={a.id} value={a.id}>{a.path.split('/').pop()}</option>)}
              </select>
            </div>
          )}
          <label className="check">
            <input type="checkbox" checked={tailOn} onChange={(e) => setTailOn(e.target.checked)} />
            片尾
          </label>
          {tailOn && (
            <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>
              <input className="grow" placeholder="片尾文字，如：第一集 · 完"
                     value={tailText} onChange={(e) => setTailText(e.target.value)} />
              <select value={tailDur} onChange={(e) => setTailDur(Number(e.target.value))}>
                <option value={1}>1s</option>
                <option value={1.5}>1.5s</option>
                <option value={2}>2s</option>
                <option value={3}>3s</option>
              </select>
              <input type="color" value={tailBg} onChange={(e) => setTailBg(e.target.value)} />
              <select value={tailImage} onChange={(e) => setTailImage(e.target.value)}>
                <option value="">纯色背景</option>
                {images.map((a) => <option key={a.id} value={a.id}>{a.path.split('/').pop()}</option>)}
              </select>
            </div>
          )}

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
            <button className="primary" disabled={busy || !ordered.length} onClick={() => void startPreview()}>
              {previewJob && ['queued', 'preparing', 'rendering'].includes(previewJob.status) ? '预览生成中…' : '预览（480p）'}
            </button>
            <button disabled={busy || !ordered.length} onClick={() => void exportRender()}>导出成片</button>
          </div>
        </div>
      </div>
    </div>
  )
}
