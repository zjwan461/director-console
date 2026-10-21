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
  narration: string
  voice_asset: string
  fit: string
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
  const [picker, setPicker] = useState<'' | 'title' | 'tail'>('')
  const [aiOpen, setAiOpen] = useState(false)
  const [aiKind, setAiKind] = useState<'both' | 'subtitle' | 'narration'>('both')
  const [aiTone, setAiTone] = useState('documentary')
  const [aiPerson, setAiPerson] = useState('third')
  const [aiLang, setAiLang] = useState('zh')
  const [aiMode, setAiMode] = useState<'fill' | 'rewrite'>('fill')
  const [aiTtsOn, setAiTtsOn] = useState(false)
  const [aiRunning, setAiRunning] = useState(false)
  const [aiMessage, setAiMessage] = useState('')
  const [aiUndo, setAiUndo] = useState<Record<string, Edit> | null>(null)
  const [aiProgress, setAiProgress] = useState({ done: 0, total: 0 })
  const [aiRows, setAiRows] = useState<Record<string, { title: string; status: string; note?: string }>>({})
  const voiceInput = useRef<HTMLInputElement | null>(null)
  const [shotPreview, setShotPreview] = useState<{ url: string; duration: number }>({ url: '', duration: 0 })
  const [previewJob, setPreviewJob] = useState<{ id: string; status: string; message: string; url?: string } | null>(null)
  const [dims, setDims] = useState<Record<string, { w: number; h: number }>>({})
  const [timeline, setTimeline] = useState<Array<{ shot_id: string; title: string; duration: number; start: number; end: number }>>([])
  const [fitMode, setFitMode] = useState('letterbox')
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
        setFitMode(String(opts.fit || 'letterbox'))
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
            narration: String(item.narration || ''),
            voice_asset: String(item.voice_asset || ''),
            fit: String(item.fit || ''),
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
          narration: editOf(s.id).narration || '',
          voice_asset: editOf(s.id).voice_asset || '',
          fit: editOf(s.id).fit || '',
        })),
      }).then(() => setSavedAt(new Date().toLocaleTimeString())).catch(() => undefined)
    }, 800)
  }, [loaded, projectId, resKey, fps, bgmId, bgmVolume, fadeIn, fadeOut, loopBgm,
      subsEnabled, subSize, subMargin, loudness, fitMode, transType, transDur, titleOn, titleText, titleDur, titleBg, titleImage,
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
    Promise.all(ordered.map((s) => api.shotPreview(s.id).catch(() => ({ duration: 0, width: 0, height: 0 })))).then((list) => {
      if (cancelled) return
      const nextDims: Record<string, { w: number; h: number }> = {}
      ordered.forEach((s, i) => {
        const w = Number((list[i] as { width?: number }).width) || 0
        const h = Number((list[i] as { height?: number }).height) || 0
        if (w && h) nextDims[s.id] = { w, h }
      })
      setDims((prev) => ({ ...prev, ...nextDims }))
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

  const uniqueImages = useMemo(() => {
    const seen = new Set<string>()
    return images.filter((a) => {
      const key = a.path.split('/').pop() || a.id
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  }, [images])

  const imageUrl = (id: string) => {
    const found = images.find((a) => a.id === id)
    return found ? (found.url || `/media/files/${found.path}`) : ''
  }

  const ordered = useMemo(() => shots.filter((s) => selected.includes(s.id)), [shots, selected])
  const editOf = (id: string): Edit => edits[id] || { in_point: '', out_point: '', subtitle: '', narration: '', voice_asset: '', fit: '' }
  const patchEdit = (id: string, patch: Partial<Edit>) =>
    setEdits((prev) => ({ ...prev, [id]: { ...editOf(id), ...patch } }))
  const voiceAudio = useRef<HTMLAudioElement | null>(null)
  const [playingVoice, setPlayingVoice] = useState('')

  const playVoice = async (shotId: string) => {
    const id = editOf(shotId).voice_asset
    if (!id) { notify('err', '没有可试听的配音'); return }
    if (playingVoice === shotId) {
      voiceAudio.current?.pause()
      setPlayingVoice('')
      return
    }
    let found = audios.find((a) => a.id === id)
    if (!found) {
      try {
        found = await api.asset(id)
        setAudios((prev) => [found as Asset, ...prev])
      } catch {
        notify('err', '配音文件已被删除'); return
      }
    }
    const url = found.url || `/media/files/${found.path}`
    voiceAudio.current?.pause()
    const audio = new Audio(url)
    voiceAudio.current = audio
    audio.onended = () => setPlayingVoice('')
    audio.onerror = () => { setPlayingVoice(''); notify('err', '试听失败', '音频文件无法播放') }
    setPlayingVoice(shotId)
    void audio.play().catch(() => { setPlayingVoice(''); notify('err', '试听失败') })
  }

  const uploadVoice = async (files: FileList | null) => {
    if (!files || !files.length || !uploadFor) return
    try {
      const asset = await api.upload(files[0], 'audio')
      patchEdit(uploadFor, { voice_asset: asset.id })
      await refreshAudios(asset.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setUploadFor('')
      if (voiceInput.current) voiceInput.current.value = ''
    }
  }

  const toggle = (id: string) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))

  const refreshAudios = async (extraId?: string) => {
    try {
      const res = await api.assets({ kind: 'audio', limit: 100 })
      let items = res.items
      if (extraId && !items.some((a) => a.id === extraId)) {
        try {
          const one = await api.asset(extraId)
          items = [one, ...items]
        } catch { /* 已删除 */ }
      }
      setAudios(items)
    } catch { /* ignore */ }
  }

  const audioLabel = (a: Asset) => {
    const meta = (a.meta || {}) as Record<string, unknown>
    const name = String(meta.origin_name || '').trim()
    if (meta.origin === 'tts') {
      const text = String(meta.text || '').trim().slice(0, 10)
      return `配音${text ? ` · ${text}…` : ''}`
    }
    return name || a.path.split('/').pop() || a.id
  }

  const notify = (kind: 'ok' | 'err', title: string, text = '') => {
    window.dispatchEvent(new CustomEvent('dsh-toast', { detail: { kind, title, text } }))
  }

  const stylePayload = () => ({ tone: aiTone, person: aiPerson, language: aiLang })

  const setRow = (shotId: string, title: string, status: string, note = '') =>
    setAiRows((prev) => ({ ...prev, [shotId]: { title, status, note } }))

  const runAI = async () => {
    if (!ordered.length) return
    const snapshot = { ...edits }
    setAiUndo(snapshot)
    setAiRunning(true)
    setAiMessage('')
    setAiRows({})
    setAiProgress({ done: 0, total: ordered.length })
    let done = 0
    let failed = 0
    let ttsFailed = 0
    try {
      for (const [index, shot] of ordered.entries()) {
        const title = shot.title || `镜头 ${shot.idx + 1}`
        setRow(shot.id, title, 'running')
        const current = editOf(shot.id)
        const wantSub = aiKind === 'both' || aiKind === 'subtitle'
        const wantNarr = aiKind === 'both' || aiKind === 'narration'
        let narrationText = current.narration
        const needNarr = wantNarr && (aiMode === 'rewrite' || !current.narration)
        const notes: string[] = []
        if (needNarr) {
          try {
            const r = await api.aiScript({ shot_id: shot.id, kind: 'narration', style: stylePayload() })
            patchEdit(shot.id, { narration: r.text })
            narrationText = r.text
            done += 1
            notes.push(`旁白 ${r.chars}/${r.budget} 字${r.compressed ? '（已压缩）' : r.over ? '（超预算）' : ''}`)
          } catch (err) {
            failed += 1
            const msg = err instanceof Error ? err.message : String(err)
            notes.push('旁白失败：' + msg.slice(0, 60))
            notify('err', `${title} 旁白生成失败`, msg.slice(0, 120))
          }
        }
        const needSub = wantSub && (aiMode === 'rewrite' || !current.subtitle)
        if (needSub) {
          try {
            const r = await api.aiScript({
              shot_id: shot.id, kind: 'subtitle', style: stylePayload(),
              narration: narrationText,
            })
            if (r.skip === 'silent') {
              notes.push('无口播，跳过字幕')
            } else {
              patchEdit(shot.id, { subtitle: r.text })
              done += 1
              notes.push(r.narration_mismatch
                ? `字幕按画面重写（旁白与画面不符）`
                : `字幕 ${r.chars}/${r.budget} 字${r.followed_narration ? '（跟随旁白）' : r.transcribed ? '（口播转写）' : r.compressed ? '（已压缩）' : r.over ? '（超预算）' : ''}`)
            }
          } catch (err) {
            failed += 1
            const msg = err instanceof Error ? err.message : String(err)
            notes.push('字幕失败：' + msg.slice(0, 60))
            notify('err', `${title} 字幕生成失败`, msg.slice(0, 120))
          }
        }
        if (needNarr && aiTtsOn && narrationText) {
          try {
            const audio = await api.aiTts({ text: narrationText, shot_id: shot.id })
            patchEdit(shot.id, { voice_asset: audio.asset_id })
            await refreshAudios(audio.asset_id)
            notes.push(audio.too_long
              ? `配音 ${audio.duration}s 超镜头 ${audio.slot}s`
              : `配音 ${audio.duration}s${audio.tempo > 1 ? `（${audio.tempo.toFixed(2)}x）` : ''}`)
          } catch (err) {
            ttsFailed += 1
            notes.push('配音失败：' + (err instanceof Error ? err.message : String(err)).slice(0, 50))
          }
        }
        if (!needSub && !needNarr) notes.push('已有内容，跳过')
        const ok = !notes.some((n) => n.includes('失败'))
        setRow(shot.id, title, ok ? 'done' : 'error', notes.join(' · '))
        setAiProgress({ done: index + 1, total: ordered.length })
      }
      const summary = `成功 ${done} 项${failed ? `，失败 ${failed} 项` : ''}${ttsFailed ? `，配音失败 ${ttsFailed} 项` : ''}`
      setAiMessage(summary)
      notify(failed || ttsFailed ? 'err' : 'ok', 'AI 生成完成', summary)
    } finally {
      setAiRunning(false)
    }
  }

  const aiOne = async (shotId: string, kind: 'subtitle' | 'narration') => {
    try {
      const r = await api.aiScript({
        shot_id: shotId, kind, style: stylePayload(),
        narration: kind === 'subtitle' ? editOf(shotId).narration : undefined,
      })
      if (r.skip === 'silent') {
        notify('ok', '跳过字幕', r.reason || '这个镜头没有明显人声')
        return
      }
      patchEdit(shotId, kind === 'subtitle' ? { subtitle: r.text } : { narration: r.text })
      if (r.narration_mismatch) {
        notify('err', '旁白与画面不一致', r.reason || '已按画面描述生成字幕，建议重写旁白')
      }
      const extra = r.followed_narration ? '（跟随旁白）' : r.transcribed ? '（口播转写）'
        : r.compressed ? `（从 ${r.original_chars} 字压缩）` : r.over ? '（仍超预算，建议手改）' : ''
      notify(r.over || r.narration_mismatch ? 'err' : 'ok', kind === 'subtitle' ? '字幕已生成' : '旁白已生成',
             `${r.chars}/${r.budget} 字${extra}`)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setError(msg)
      notify('err', 'AI 生成失败', msg.slice(0, 120))
    }
  }

  const ttsOne = async (shotId: string) => {
    const text = editOf(shotId).narration.trim()
    if (!text) { setError('先写旁白文案，再点配音'); return }
    try {
      const audio = await api.aiTts({ text, shot_id: shotId })
      patchEdit(shotId, { voice_asset: audio.asset_id })
      await refreshAudios(audio.asset_id)
      if (audio.too_long) {
        notify('err', '配音超出镜头时长',
               `配音 ${audio.duration}s / 镜头 ${audio.slot}s，请缩短旁白或换更长的镜头`)
      } else {
        const tempo = audio.tempo > 1.0 ? `，成片建议 ${audio.tempo.toFixed(2)}x` : ''
        notify('ok', '配音完成', `${audio.duration}s${tempo}`)
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setError(msg)
      notify('err', '配音失败', msg.slice(0, 120))
    }
  }

  const startPreview = async () => {
    if (!ordered.length) return
    setBusy(true)
    setError('')
    setPreviewJob(null)
    const res = RESOLUTIONS.find((r) => r.key === resKey) || RESOLUTIONS[1]
    try {
      const render = await api.createRender(projectId, ordered.map((s) => s.id), {
        width: res.width, height: res.height, fps, preview: true, fit: fitMode,
        transition: { type: transType, duration: transDur },
        title: { enabled: titleOn, text: titleText, duration: titleDur, bg: titleBg, bg_asset: titleImage },
        tail: { enabled: tailOn, text: tailText, duration: tailDur, bg: tailBg, bg_asset: tailImage },
      }, ordered.map((s) => ({
        shot_id: s.id,
        in_point: Number(editOf(s.id).in_point) || 0,
        out_point: editOf(s.id).out_point ? Number(editOf(s.id).out_point) : undefined,
        subtitle: editOf(s.id).subtitle || s.title || '',
        voice_asset: editOf(s.id).voice_asset || '',
        fit: editOf(s.id).fit || '',
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
        width: res.width, height: res.height, fps, fit: fitMode,
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
        fit: editOf(s.id).fit || '',
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
          <button className="primary" onClick={() => setAiOpen(true)}>AI 生成</button>
          {savedAt && <span className="meta">已自动保存 {savedAt}</span>}
        </div>
      </div>

      <input ref={voiceInput} type="file" hidden accept="audio/*"
             onChange={(e) => void uploadVoice(e.target.files)} />

      {aiOpen && (
        <div className="picker-overlay" onClick={() => !aiRunning && setAiOpen(false)}>
          <div className="picker" style={{ width: 460 }} onClick={(e) => e.stopPropagation()}>
            <div className="picker-head">
              <b>AI 生成</b>
              <button className="ghost tiny" onClick={() => setAiOpen(false)}>关闭</button>
            </div>
            <div className="field"><label><span>生成内容</span></label>
              <select value={aiKind} onChange={(e) => setAiKind(e.target.value as typeof aiKind)}>
                <option value="both">字幕 + 旁白</option>
                <option value="subtitle">只生成字幕</option>
                <option value="narration">只生成旁白</option>
              </select>
            </div>
            <div className="row">
              <select value={aiTone} onChange={(e) => setAiTone(e.target.value)}>
                <option value="documentary">纪实解说</option>
                <option value="suspense">悬念</option>
                <option value="casual">口语</option>
              </select>
              <select value={aiPerson} onChange={(e) => setAiPerson(e.target.value)}>
                <option value="third">第三人称</option>
                <option value="first">第一人称</option>
              </select>
              <select value={aiLang} onChange={(e) => setAiLang(e.target.value)}>
                <option value="zh">中文</option>
                <option value="bilingual">中英双语</option>
              </select>
            </div>
            <div className="row">
              <select value={aiMode} onChange={(e) => setAiMode(e.target.value as typeof aiMode)}>
                <option value="fill">只填空白</option>
                <option value="rewrite">全部重写</option>
              </select>
              {(aiKind === 'narration' || aiKind === 'both') && (
                <label className="check" style={{ margin: 0 }}>
                  <input type="checkbox" checked={aiTtsOn} onChange={(e) => setAiTtsOn(e.target.checked)} />
                  同时配音
                </label>
              )}
            </div>
            {aiRunning && (
              <div className="ai-progress">
                <span className="spin" />
                <span>{aiProgress.done}/{aiProgress.total} 镜处理中…</span>
              </div>
            )}
            {Object.keys(aiRows).length > 0 && (
              <div className="ai-rows">
                {Object.entries(aiRows).map(([id, row]) => (
                  <div key={id} className={`ai-row ${row.status}`}>
                    <span className="ai-dot" />
                    <b>{row.title}</b>
                    <span>{row.note || (row.status === 'running' ? '生成中…' : '')}</span>
                  </div>
                ))}
              </div>
            )}
            {aiMessage && <div className="notice">{aiMessage}</div>}
            <div className="row-actions">
              <button className="primary" disabled={aiRunning || !ordered.length} onClick={() => void runAI()}>
                {aiRunning ? '生成中…' : `开始（${ordered.length} 镜）`}
              </button>
              {aiUndo && (
                <button className="ghost" disabled={aiRunning}
                        onClick={() => { setEdits(aiUndo); setAiUndo(null); setAiMessage('已撤销') }}>
                  撤销上次 AI
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {picker && (
        <div className="picker-overlay" onClick={() => setPicker('')}>
          <div className="picker" onClick={(e) => e.stopPropagation()}>
            <div className="picker-head">
              <b>{picker === 'title' ? '选择片头背景' : '选择片尾背景'}</b>
              <button className="ghost tiny" onClick={() => setPicker('')}>关闭</button>
            </div>
            <div className="picker-grid">
              <button className="picker-item color-none"
                      onClick={() => { picker === 'title' ? setTitleImage('') : setTailImage(''); setPicker('') }}>
                纯色背景
              </button>
              {uniqueImages.map((a) => (
                <button key={a.id} className="picker-item"
                        onClick={() => {
                          picker === 'title' ? setTitleImage(a.id) : setTailImage(a.id)
                          setPicker('')
                        }}>
                  <img src={a.url || `/media/files/${a.path}`} alt={a.path} />
                  <span>{a.path.split('/').pop()}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
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
                    {(() => {
                      const d = dims[shot.id]
                      if (!d) return null
                      const canvas = RESOLUTIONS.find((r) => r.key === resKey) || RESOLUTIONS[1]
                      const srcRatio = d.w / d.h
                      const canvasRatio = canvas.width / canvas.height
                      const off = Math.abs(srcRatio - canvasRatio) > 0.05
                      const label = srcRatio > 1.2 ? '横屏' : srcRatio < 0.85 ? '竖屏' : '方形'
                      return (
                        <span className={`badge ${off ? 'warn' : ''}`} title={`${d.w}×${d.h}`}>
                          {label} {off ? '· 比例不符' : ''}
                        </span>
                      )
                    })()}
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
                          <div className="voice-pick">
                            <input className="grow" placeholder={shot.title || '这一镜的字幕'}
                                   value={edit.subtitle}
                                   onChange={(e) => patchEdit(shot.id, { subtitle: e.target.value })} />
                            <button className="ghost tiny" onClick={() => void aiOne(shot.id, 'subtitle')}>AI 写</button>
                          </div>
                        </label>
                      </div>
                      <div className="shot-row">
                        <label className="grow">
                          旁白
                          <div className="voice-pick">
                            <select className="grow" value={edit.voice_asset}
                                    onChange={(e) => patchEdit(shot.id, { voice_asset: e.target.value })}>
                              <option value="">无旁白音频</option>
                              {audios.map((a) => (
                                <option key={a.id} value={a.id}>{audioLabel(a)}</option>
                              ))}
                            </select>
                            <button className="ghost tiny"
                                    onClick={() => { setUploadFor(shot.id); voiceInput.current?.click() }}>
                              上传
                            </button>
                            <button className="ghost tiny" onClick={() => void aiOne(shot.id, 'narration')}>AI 写</button>
                            <button className="ghost tiny" disabled={!edit.narration.trim()}
                                    title={edit.narration.trim() ? '合成配音' : '先写旁白文案'}
                                    onClick={() => void ttsOne(shot.id)}>
                              配音
                            </button>
                            <button className="ghost tiny" disabled={!edit.voice_asset}
                                    onClick={() => void playVoice(shot.id)}>
                              {playingVoice === shot.id ? '停止' : '试听'}
                            </button>
                            {edit.narration.trim() && !edit.voice_asset && <span className="badge warn">未配音</span>}
                            {!edit.narration.trim() && edit.voice_asset && <span className="badge">仅音频</span>}
                          </div>
                        </label>
                        <label>
                          旁白文案
                          <input placeholder="旁白文本（配音用）" value={edit.narration}
                                 onChange={(e) => patchEdit(shot.id, { narration: e.target.value })} />
                        </label>
                        <label>
                          适配
                          <select value={edit.fit} onChange={(e) => patchEdit(shot.id, { fit: e.target.value })}>
                            <option value="">跟随全局</option>
                            <option value="letterbox">补边</option>
                            <option value="crop">裁切</option>
                            <option value="blur">模糊</option>
                          </select>
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
            <div className="canvas-box" style={{
              aspectRatio: `${(RESOLUTIONS.find((r) => r.key === resKey) || RESOLUTIONS[1]).width} / ${
                (RESOLUTIONS.find((r) => r.key === resKey) || RESOLUTIONS[1]).height}`,
            }}>
              <video key={previewJob?.url || shotPreview.url} className="preview-video"
                     src={previewJob?.status === 'succeeded' && previewJob.url ? previewJob.url : shotPreview.url} controls />
            </div>
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

          <h3>画布适配</h3>
          <select className="grow" value={fitMode} onChange={(e) => setFitMode(e.target.value)}>
            <option value="letterbox">补边（保留完整画面，可能有黑边）</option>
            <option value="crop">裁切填满（切掉超出部分）</option>
            <option value="blur">模糊背景补边（无黑边）</option>
          </select>

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
          {titleOn && !titleText.trim() && <div className="meta" style={{ color: 'var(--warn, #facc15)' }}>填写文字后才会生成片头</div>}
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
              <button className="ghost tiny" onClick={() => setPicker('title')}>
                {titleImage ? '换图片' : '选图片'}
              </button>
              {titleImage && (
                <>
                  <img className="bg-thumb" src={imageUrl(titleImage)} alt="片头背景" />
                  <button className="ghost tiny" onClick={() => setTitleImage('')}>清除</button>
                </>
              )}
            </div>
          )}
          <label className="check">
            <input type="checkbox" checked={tailOn} onChange={(e) => setTailOn(e.target.checked)} />
            片尾
          </label>
          {tailOn && !tailText.trim() && <div className="meta" style={{ color: 'var(--warn, #facc15)' }}>填写文字后才会生成片尾</div>}
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
              <button className="ghost tiny" onClick={() => setPicker('tail')}>
                {tailImage ? '换图片' : '选图片'}
              </button>
              {tailImage && (
                <>
                  <img className="bg-thumb" src={imageUrl(tailImage)} alt="片尾背景" />
                  <button className="ghost tiny" onClick={() => setTailImage('')}>清除</button>
                </>
              )}
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
