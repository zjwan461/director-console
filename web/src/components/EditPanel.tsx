import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import type { Asset, Project, Shot } from '../types'
import BgmTimeline from './BgmTimeline'

const RESOLUTIONS = [
  { key: '480p', label: '480p · 854×480', width: 854, height: 480 },
  { key: '720p', label: '720p · 1280×720', width: 1280, height: 720 },
  { key: '1080p', label: '1080p · 1920×1080', width: 1920, height: 1080 },
]

interface BgmTrack {
  id: string
  asset_id: string
  volume_db: number
  start: number
  end: number | null
  fade_in: number
  fade_out: number
  loop: boolean
}

interface Edit {
  in_point: string
  out_point: string
  subtitle: string
  narration: string
  voice_asset: string
  fit: string
  mode: string
  tts_voice: string
  narration_on: boolean
  lip_on: boolean
  volume_db: string
  subtitle_lock: boolean
  burned_mode: string
  speed: string
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
  const [voiceOptions, setVoiceOptions] = useState<Array<{ id: string; name: string }>>([])
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
  const [bgmTracks, setBgmTracks] = useState<BgmTrack[]>([])
  const [duckBgm, setDuckBgm] = useState(true)
  const [activeTrackId, setActiveTrackId] = useState('')
  const [playhead, setPlayhead] = useState(0)
  const [subsEnabled, setSubsEnabled] = useState(true)
  const [subSize, setSubSize] = useState(42)
  const [subAutoFit, setSubAutoFit] = useState(true)
  const [burnedDefault, setBurnedDefault] = useState(false)
  const [durations, setDurations] = useState<Record<string, number>>({})
  const [subMargin, setSubMargin] = useState(48)
  const [loudness, setLoudness] = useState(true)
  const [loaded, setLoaded] = useState(false)
  const [savedAt, setSavedAt] = useState('')
  const [error, setError] = useState('')
  const [previewBusy, setPreviewBusy] = useState(false)
  const [exportBusy, setExportBusy] = useState(false)
  const [activeShot, setActiveShot] = useState('')
  const [uploadFor, setUploadFor] = useState('')
  const [picker, setPicker] = useState<'' | 'title' | 'tail'>('')
  const [aiOpen, setAiOpen] = useState(() => new URLSearchParams(window.location.search).has('ai'))
  const [aiKind, setAiKind] = useState<'both' | 'subtitle' | 'narration' | 'merge'>('both')
  const [mergeBurned, setMergeBurned] = useState(true)
  const [aiTitles, setAiTitles] = useState(true)
  const [aiAutoSpeed, setAiAutoSpeed] = useState(true)
  const [aiBgmId, setAiBgmId] = useState('')
  const [framesBusy, setFramesBusy] = useState(false)
  const [aiTone, setAiTone] = useState('documentary')
  const [aiPerson, setAiPerson] = useState('third')
  const [subLang, setSubLang] = useState<'zh' | 'bilingual'>('zh')
  const [aiMode, setAiMode] = useState<'fill' | 'rewrite'>('fill')
  const [aiTtsOn, setAiTtsOn] = useState(false)
  const [aiRunning, setAiRunning] = useState(false)
  const [aiMessage, setAiMessage] = useState('')
  const [aiUndo, setAiUndo] = useState<Record<string, Edit> | null>(null)
  const [aiProgress, setAiProgress] = useState({ done: 0, total: 0 })
  const [aiRows, setAiRows] = useState<Record<string, { title: string; status: string; note?: string }>>({})
  const [contentMode, setContentMode] = useState<'narration' | 'lip' | 'silent'>('narration')
  const [aiBusy, setAiBusy] = useState('')
  const [aiFrames, setAiFrames] = useState(0)
  const [titleBusy, setTitleBusy] = useState('')
  const [rhythm, setRhythm] = useState<{ summary: string; items: Array<{ shot_id: string; title: string; duration: number; level: string; advice: string }>; bgm_tips: Array<{ level: string; text: string }> } | null>(null)
  const [rhythmBusy, setRhythmBusy] = useState(false)
  const [aiFrameGroups, setAiFrameGroups] = useState<Array<{ shotId: string; title: string; urls: string[] }>>([])
  const [showPrompt, setShowPrompt] = useState(false)
  const voiceInput = useRef<HTMLInputElement | null>(null)
  const previewVideoRef = useRef<HTMLVideoElement | null>(null)
  const pendingSeek = useRef<number | null>(null)
  const [shotPreview, setShotPreview] = useState<{ url: string; duration: number }>({ url: '', duration: 0 })
  const [previewJob, setPreviewJob] = useState<{ id: string; status: string; message: string; url?: string } | null>(null)
  const [dims, setDims] = useState<Record<string, { w: number; h: number }>>({})
  const [timeline, setTimeline] = useState<Array<{ shot_id: string; title: string; duration: number; start: number; end: number }>>([])
  const [timelineMeta, setTimelineMeta] = useState<{ total: number; title_duration: number; tail_duration: number; full_total: number } | null>(null)
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
    api.ttsVoices().then((res) => setVoiceOptions(res.items || [])).catch(() => undefined)
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
        setContentMode((String(opts.content_mode || 'narration') as typeof contentMode))
        const bgm = (opts.bgm || {}) as Record<string, unknown>
        const rawTracks = Array.isArray(opts.bgm_tracks) ? (opts.bgm_tracks as Array<Record<string, unknown>>) : []
        if (rawTracks.length) {
          setBgmTracks(rawTracks.map((item, index) => ({
            id: String(item.id || `t${index + 1}`),
            asset_id: String(item.asset_id || ''),
            volume_db: Number(item.volume_db ?? -14),
            start: Number(item.start ?? 0),
            end: item.end === null || item.end === undefined ? null : Number(item.end),
            fade_in: Number(item.fade_in ?? 0.5),
            fade_out: Number(item.fade_out ?? 0.5),
            loop: Boolean(item.loop ?? true),
          })))
        } else if (bgm.asset_id) {
          // 老数据：单条 bgm 升级成一条轨道
          setBgmTracks([{
            id: 't1',
            asset_id: String(bgm.asset_id),
            volume_db: Number(bgm.volume_db ?? -14),
            start: 0,
            end: null,
            fade_in: Number(bgm.fade_in ?? 0.5),
            fade_out: Number(bgm.fade_out ?? 0.5),
            loop: Boolean(bgm.loop ?? true),
          }])
        } else {
          setBgmTracks([])
        }
        setDuckBgm(Boolean(bgm.duck ?? true))
        const subs = (opts.subtitles || {}) as Record<string, unknown>
        const style = (subs.style || {}) as Record<string, unknown>
        setSubsEnabled(Boolean(subs.enabled ?? true))
        setSubSize(Number(style.size || 42))
        setSubMargin(Number(style.margin_v || 48))
        setSubAutoFit(Boolean(subs.autofit ?? true))
        setSubLang((String(subs.language || 'zh') === 'bilingual' ? 'bilingual' : 'zh'))
        setBurnedDefault(Boolean(opts.burned_default))
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
            mode: String(item.mode || ''),
            tts_voice: String(item.tts_voice || ''),
            narration_on: item.narration_on !== undefined
              ? Boolean(item.narration_on)
              : (String(item.mode || '') ? String(item.mode) === 'narration' : true),
            lip_on: item.lip_on !== undefined
              ? Boolean(item.lip_on)
              : String(item.mode || '') === 'lip',
            volume_db: String(item.volume_db ?? '0'),
            subtitle_lock: Boolean(item.subtitle_lock),
            burned_mode: item.burned_subtitle === true ? 'on' : (String(item.burned_mode || 'inherit')),
            speed: String(item.speed ?? '1'),
          }
        }
        // 有旁白且没手动锁定时，字幕以旁白为准（修正历史遗留的不一致）
        for (const entry of Object.values(map)) {
          if (entry.narration_on && !entry.subtitle_lock && entry.narration.trim()) {
            entry.subtitle = entry.narration
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
          bgm: { duck: duckBgm, duck_db: -14 },
          bgm_tracks: bgmTracks.filter((t) => t.asset_id).map((t) => ({
            id: t.id,
            asset_id: t.asset_id,
            volume_db: t.volume_db,
            start: t.start,
            end: t.end,
            fade_in: t.fade_in,
            fade_out: t.fade_out,
            loop: t.loop,
          })),
          subtitles: { enabled: subsEnabled, autofit: subAutoFit, language: subLang,
                        style: { size: subSize, margin_v: subMargin } },
          burned_default: burnedDefault,
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
          mode: editOf(s.id).mode || '',
          tts_voice: editOf(s.id).tts_voice || '',
          narration_on: editOf(s.id).narration_on,
          lip_on: editOf(s.id).lip_on,
          volume_db: Number(editOf(s.id).volume_db) || 0,
          speed: Number(editOf(s.id).speed) || 1,
          subtitle_lock: editOf(s.id).subtitle_lock,
          burned_subtitle: isBurned(s.id),
        })),
      }).then(() => setSavedAt(new Date().toLocaleTimeString())).catch(() => undefined)
    }, 800)
  }, [loaded, projectId, resKey, fps, bgmTracks, duckBgm,
      subsEnabled, subSize, subMargin, subAutoFit, subLang, burnedDefault, loudness, fitMode, contentMode, transType, transDur, titleOn, titleText, titleDur, titleBg, titleImage,
      tailOn, tailText, tailDur, tailBg, tailImage, edits, selected, shots])

  useEffect(() => {
    if (!activeShot) return
    api.shotPreview(activeShot)
      .then((res) => setShotPreview({ url: res.url, duration: res.duration }))
      .catch(() => setShotPreview({ url: '', duration: 0 }))
  }, [activeShot])

  // 预览源是「整片预览」时，视频时间 = 片头 + 正片时间
  const filmPreviewUrl = previewJob?.status === 'succeeded' ? (previewJob.url || '') : ''
  const usingFilmPreview = Boolean(filmPreviewUrl)
  const titleOffset = timelineMeta
    ? timelineMeta.title_duration
    : (titleOn && titleText.trim() ? titleDur : 0)

  // 时间轴点击 → 换算成「第几个镜头 + 镜头内偏移」，切镜头并定位
  const filmTimeOf = useCallback((localSeconds: number) => {
    if (usingFilmPreview) {
      // 整片预览前面有片头卡，时间轴从片头结束后算起
      const film = localSeconds - titleOffset
      const last = timeline.length ? timeline[timeline.length - 1].end : 0
      return Math.max(0, Math.min(film, last))
    }
    const item = timeline.find((i) => i.shot_id === activeShot)
    if (!item) return localSeconds
    return item.start + Math.min(localSeconds, item.duration)
  }, [timeline, activeShot, usingFilmPreview, titleOffset])

  const seekFilm = useCallback((filmSeconds: number) => {
    if (!timeline.length) return
    setPlayhead(Math.max(0, filmSeconds))
    if (usingFilmPreview) {
      const video = previewVideoRef.current
      // 目标时间要加上片头卡的长度，别把片头当成正片
      if (video) video.currentTime = Math.max(0, Math.min(filmSeconds + titleOffset, video.duration || Infinity))
      return
    }
    const target = timeline.find((item) => filmSeconds >= item.start && filmSeconds < item.end)
      || timeline[timeline.length - 1]
    const local = Math.max(0, Math.min(filmSeconds - target.start, Math.max(target.duration - 0.05, 0)))
    if (target.shot_id !== activeShot) {
      pendingSeek.current = local
      setActiveShot(target.shot_id)
    } else {
      const video = previewVideoRef.current
      if (video) video.currentTime = local
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeline, activeShot, usingFilmPreview])

  // 切换预览源（例如刚生成整片预览）后，播放头回到开头
  useEffect(() => {
    setPlayhead(0)
    pendingSeek.current = null
  }, [filmPreviewUrl])

  // 切镜头后（video 的 key 变了、元素重建）把待定的镜头内时间应用上去
  useEffect(() => {
    const local = pendingSeek.current
    if (local === null) return
    const video = previewVideoRef.current
    if (!video) return
    const apply = () => {
      try { video.currentTime = local } catch { /* 忽略 */ }
      pendingSeek.current = null
      setPlayhead(filmTimeOf(local))
    }
    if (video.readyState >= 1) apply()
    else {
      video.addEventListener('loadedmetadata', apply, { once: true })
      return () => video.removeEventListener('loadedmetadata', apply)
    }
  }, [shotPreview.url, previewJob?.url, filmTimeOf])

  useEffect(() => () => {
    if (pollTimer.current) window.clearTimeout(pollTimer.current)
  }, [])

  // 时间轴以后端为准：转场重叠、变速、片头偏移都在服务端算一次
  const refreshTimeline = useCallback(async () => {
    if (!projectId) return
    try {
      const res = await api.projectTimeline(projectId)
      setTimeline(res.items.map((i) => ({
        shot_id: i.shot_id,
        title: i.title || '镜头',
        duration: i.duration,
        start: i.start,
        end: i.end,
      })))
      setTimelineMeta({
        total: res.total,
        title_duration: res.title_duration,
        tail_duration: res.tail_duration,
        full_total: res.full_total,
      })
    } catch {
      /* 接口不可用时保留旧时间轴 */
    }
  }, [projectId])

  // 镜头尺寸/时长仍要本地探测（预览比例、入出点上限用得到）
  useEffect(() => {
    let cancelled = false
    if (!ordered.length) { setTimeline([]); return }
    Promise.all(ordered.map((s) => api.shotPreview(s.id).catch(() => ({ duration: 0, width: 0, height: 0 })))).then((list) => {
      if (cancelled) return
      const nextDims: Record<string, { w: number; h: number }> = {}
      ordered.forEach((s, i) => {
        const w = Number((list[i] as { width?: number }).width) || 0
        const h = Number((list[i] as { height?: number }).height) || 0
        if (w && h) nextDims[s.id] = { w, h }
      })
      setDims((prev) => ({ ...prev, ...nextDims }))
      const nextDur: Record<string, number> = {}
      ordered.forEach((s, i) => {
        const d = Number((list[i] as { duration?: number }).duration) || 0
        if (d) nextDur[s.id] = d
      })
      setDurations((prev) => ({ ...prev, ...nextDur }))
    })
    return () => { cancelled = true }
  }, [selected, shots])

  // 自动保存之后刷新时间轴，确保和已保存的编辑状态一致
  useEffect(() => {
    if (!loaded) return
    void refreshTimeline()
  }, [loaded, refreshTimeline, selected, transType, transDur, titleOn, titleText, titleDur, tailOn, tailText, tailDur])

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

  const updateTrack = (id: string, patch: Partial<BgmTrack>) =>
    setBgmTracks((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch } : t)))

  // 全片时长 = 最后一个镜头块的结束时间（转场会让块之间有重叠，不能用求和）
  // 时间轴上的旁白轨：每镜一段，长度跟镜头块一致
  const narrationClips = useMemo(() => timeline.map((item, index) => {
    const edit = edits[item.shot_id]
    const assetId = edit?.narration_on ? (edit.voice_asset || '') : ''
    const asset = audios.find((a) => a.id === assetId)
    const raw = asset ? Number((asset.meta || {}).duration || 0) : 0
    // 开了旁白但没有配音：标成待办，时间轴上画一条极淡的提示条
    const pending = Boolean(edit?.narration_on) && !assetId
    // 转场会让相邻镜头块重叠，旁白块在下一镜起点处截断，避免叠在一起
    const nextStart = timeline[index + 1]?.start
    const visibleEnd = nextStart !== undefined ? Math.min(item.end, nextStart) : item.end
    return {
      shot_id: item.shot_id,
      title: item.title,
      start: item.start,
      end: Math.max(visibleEnd, item.start + 0.2),
      asset_id: assetId,
      audio_duration: raw,
      pending,
      has_text: Boolean((edit?.narration || '').trim()),
    }
  }), [timeline, edits, audios])

  const filmDuration = useMemo(() => {
    if (timelineMeta) return timelineMeta.total
    if (!timeline.length) return 0
    return timeline[timeline.length - 1].end
  }, [timeline, timelineMeta])

  const modeLabel = (mode: string) =>
    mode === 'narration' ? '解说' : mode === 'lip' ? '口播' : '纯画面'

  const isBurned = (shotId: string) => {
    const mode = editOf(shotId).burned_mode
    if (mode === 'on') return true
    if (mode === 'off') return false
    return burnedDefault
  }

  const changeLang = (next: 'zh' | 'bilingual') => {
    setSubLang(next)
    // 双语是两行，字号自动压到 44 以内，避免占掉太多画面
    if (next === 'bilingual') setSubSize((prev) => Math.min(prev, 44))
  }

  const fitSubtitle = (text: string, shotId: string) => {
    if (!subAutoFit) return text
    const seconds = durations[shotId] || 0
    if (!seconds) return text
    const budget = Math.max(8, Math.floor(seconds * 4.5))
    const value = text.trim()
    if (value.length <= budget) return value
    const cut = value.slice(0, budget).replace(/[，。！？、,.!?\s]+$/, '')
    return cut.endsWith('…') ? cut : cut + '…'
  }

  const setNarration = (shotId: string, on: boolean) => {
    const edit = editOf(shotId)
    if (on && !edit.subtitle_lock && edit.narration.trim()) {
      patchEdit(shotId, { narration_on: true, subtitle: fitSubtitle(edit.narration, shotId) })
    } else {
      patchEdit(shotId, { narration_on: on })
    }
  }

  const setNarrationText = (shotId: string, text: string) => {
    const edit = editOf(shotId)
    patchEdit(shotId, edit.subtitle_lock
      ? { narration: text }
      : { narration: text, subtitle: fitSubtitle(text, shotId) })
  }
  const setLip = (shotId: string, on: boolean) => patchEdit(shotId, { lip_on: on })

  const modeOf = (shotId: string): 'narration' | 'lip' | 'silent' => {
    const edit = editOf(shotId)
    if (edit.narration_on) return 'narration'
    if (edit.lip_on) return 'lip'
    return 'silent'
  }

  useEffect(() => {
    if (!subAutoFit || !loaded) return
    setEdits((prev) => {
      let changed = false
      const next: Record<string, Edit> = { ...prev }
      for (const shot of shots) {
        const entry = next[shot.id]
        if (!entry || entry.subtitle_lock || !entry.narration_on) continue
        const target = fitSubtitle(entry.narration, shot.id)
        if (target && target !== entry.subtitle) {
          next[shot.id] = { ...entry, subtitle: target }
          changed = true
        }
      }
      return changed ? next : prev
    })
  }, [durations, subAutoFit, loaded, shots])

  const ordered = useMemo(() => shots.filter((s) => selected.includes(s.id)), [shots, selected])
  const editOf = (id: string): Edit => edits[id] || { in_point: '', out_point: '', subtitle: '', narration: '', voice_asset: '', fit: '', mode: '', tts_voice: '', narration_on: true, lip_on: false, volume_db: '0', subtitle_lock: false, burned_mode: 'inherit' }
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

  const stylePayload = () => ({ tone: aiTone, person: aiPerson, language: subLang })

  const setRow = (shotId: string, title: string, status: string, note = '') =>
    setAiRows((prev) => ({ ...prev, [shotId]: { title, status, note } }))

  const loadFrames = async () => {
    if (!ordered.length) return
    setFramesBusy(true)
    setAiFrameGroups([])
    try {
      const count = aiFrames || 3
      const groups: Array<{ shotId: string; title: string; urls: string[] }> = []
      for (const shot of ordered) {
        const res = await api.shotFrames(shot.id, count)
        groups.push({
          shotId: shot.id,
          title: shot.title || `镜头 ${shot.idx + 1}`,
          urls: res.items.map((i) => i.url),
        })
        setAiFrameGroups([...groups])
      }
      setAiFrameGroups(groups)
    } catch (err) {
      notify('err', '截帧失败', err instanceof Error ? err.message : String(err))
    } finally {
      setFramesBusy(false)
    }
  }

  const promptPreview = () => {
    const first = ordered[0]
    const canvas = RESOLUTIONS.find((r) => r.key === resKey) || RESOLUTIONS[1]
    return JSON.stringify({
      kind: aiKind,
      style: { tone: aiTone, person: aiPerson, language: subLang },
      frames_per_shot: aiFrames,
      shots: ordered.slice(0, 3).map((s) => ({
        title: s.title,
        description: String(s.values?.prompt || '').slice(0, 200),
        duration: Number(editOf(s.id).out_point || 5) - Number(editOf(s.id).in_point || 0),
      })),
      canvas: `${canvas.width}x${canvas.height}`,
      note: first ? `共 ${ordered.length} 镜` : '未选择镜头',
    }, null, 2)
  }

  const aiTitle = async (kind: 'title' | 'tail') => {
    setTitleBusy(kind)
    try {
      const r = await api.aiTitle(projectId, kind)
      if (kind === 'title') setTitleText(r.text)
      else setTailText(r.text)
      notify('ok', kind === 'title' ? '片头文案已生成' : '片尾文案已生成', r.text)
    } catch (err) {
      notify('err', '生成失败', err instanceof Error ? err.message : String(err))
    } finally {
      setTitleBusy('')
    }
  }

  const runRhythm = async () => {
    setRhythmBusy(true)
    try {
      const r = await api.rhythm(projectId)
      setRhythm({ summary: r.summary, items: r.items, bgm_tips: r.bgm_tips || [] })
      notify('ok', '节奏检查完成', r.summary)
    } catch (err) {
      notify('err', '节奏检查失败', err instanceof Error ? err.message : String(err))
    } finally {
      setRhythmBusy(false)
    }
  }

  const runAI = async () => {
    if (!ordered.length) return
    const snapshot = { ...edits }
    setAiUndo(snapshot)
    setAiRunning(true)
    setAiMessage('')
    if (aiKind === 'merge') {
      setBurnedDefault(mergeBurned)
      await exportRender(mergeBurned)
      setAiRunning(false)
      setAiOpen(false)
      notify('ok', '仅合并', mergeBurned ? '已提交导出（按视频自带字幕，不烧录）' : '已提交导出（不生成字幕/旁白）')
      return
    }
    setAiRows({})
    setAiProgress({ done: 0, total: ordered.length })
    if (contentMode === 'silent') {
      notify('ok', '纯画面模式', '当前设置为纯画面，不生成字幕/旁白')
      setAiRunning(false)
      return
    }
    let done = 0
    let failed = 0
    let ttsFailed = 0
    // 用户指定的 BGM：自动写入一条轨道，参数按是否有旁白给合理默认
    if (aiBgmId) {
      const hasNarration = ordered.some((s) => editOf(s.id).narration_on || editOf(s.id).voice_asset)
      setBgmTracks([{
        id: `t${Date.now().toString(36)}`,
        asset_id: aiBgmId,
        volume_db: hasNarration ? -18 : -12,
        start: 0,
        end: null,
        fade_in: 1,
        fade_out: 2,
        loop: true,
      }])
      setDuckBgm(true)
      done += 1
    }
    try {
      for (const [index, shot] of ordered.entries()) {
        const title = shot.title || `镜头 ${shot.idx + 1}`
        const startedAt = Date.now()
        setRow(shot.id, title, 'running')
        const current = editOf(shot.id)
        const shotMode = modeOf(shot.id)
        const wantSub = !isBurned(shot.id) && (editOf(shot.id).narration_on || editOf(shot.id).lip_on) && aiKind !== 'narration'
        const wantNarr = shotMode === 'narration' && (aiKind === 'both' || aiKind === 'narration')
        let narrationText = current.narration
        const needNarr = wantNarr && (aiMode === 'rewrite' || !current.narration)
        const notes: string[] = []
        if (needNarr) {
          try {
            const r = await api.aiScript({ shot_id: shot.id, kind: 'narration', style: stylePayload(), frames: aiFrames })
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
              narration: editOf(shot.id).narration_on
                ? narrationText
                : (editOf(shot.id).lip_on ? '' : undefined), frames: aiFrames,
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
            const audio = await api.aiTts({ text: narrationText, shot_id: shot.id, voice: editOf(shot.id).tts_voice || undefined })
            patchEdit(shot.id, { voice_asset: audio.asset_id })
            await refreshAudios(audio.asset_id)
            notes.push(audio.too_long
              ? `配音 ${audio.duration}s 超镜头 ${audio.slot}s`
              : `配音 ${audio.duration}s${audio.tempo > 1 ? `（${audio.tempo.toFixed(2)}x）` : ''}`)

            // 自动匹配镜头时长：旁白更长时，给画面提速（只加速，1.0~1.25x）
            if (aiAutoSpeed && audio.duration > 0) {
              const slot = Number(audio.slot) || durations[shot.id] || 0
              const ratio = slot > 0.5 ? audio.duration / Math.max(slot - 0.3, 0.5) : 1
              const steps = [1.0, 1.05, 1.1, 1.15, 1.2, 1.25]
              const speed = steps.find((v) => v >= ratio) ?? 1.0
              if (speed > 1.0 && slot >= 1.5) {
                patchEdit(shot.id, { speed: String(speed) })
                notes.push(`画面 ${speed.toFixed(2)}x 对齐旁白`)
              } else if (ratio > 1.25) {
                notes.push('旁白超 1.25x 仍放不下，建议缩短文案')
              } else if (slot > 0 && slot < 1.5) {
                notes.push('镜头太短，未自动调速')
              }
            }
          } catch (err) {
            ttsFailed += 1
            notes.push('配音失败：' + (err instanceof Error ? err.message : String(err)).slice(0, 50))
          }
        }
        if (!needSub && !needNarr) notes.push('已有内容，跳过')
        const ok = !notes.some((n) => n.includes('失败'))
        const seconds = ((Date.now() - startedAt) / 1000).toFixed(1)
        setRow(shot.id, title, ok ? 'done' : 'error', `${notes.join(' · ')} · ${seconds}s`)
        setAiProgress({ done: index + 1, total: ordered.length })
      }
      if (aiTitles) {
        try {
          if (aiMode === 'rewrite' || !titleText.trim()) setTitleText((await api.aiTitle(projectId, 'title')).text)
          if (aiMode === 'rewrite' || !tailText.trim()) setTailText((await api.aiTitle(projectId, 'tail')).text)
          done += 1
        } catch { failed += 1 }
      }
      const summary = `成功 ${done} 项${failed ? `，失败 ${failed} 项` : ''}${ttsFailed ? `，配音失败 ${ttsFailed} 项` : ''}`
      setAiMessage(summary)
      notify(failed || ttsFailed ? 'err' : 'ok', 'AI 生成完成', summary)
    } finally {
      setAiRunning(false)
    }
  }

  const aiOne = async (shotId: string, kind: 'subtitle' | 'narration') => {
    const key = `${shotId}:${kind}`
    if (kind === 'subtitle' && modeOf(shotId) === 'silent') {
      notify('ok', '纯画面镜头', '这个镜头设置为纯画面，不生成字幕')
      return
    }
    setAiBusy(key)
    try {
      const narration = kind === 'subtitle' && modeOf(shotId) === 'narration'
        ? editOf(shotId).narration
        : undefined
      const r = await api.aiScript({
        shot_id: shotId, kind, style: stylePayload(), frames: aiFrames,
        narration,
      })
      if (r.skip === 'silent') {
        notify('ok', '跳过字幕', r.reason || '这个镜头没有明显人声')
        return
      }
      if (kind === 'subtitle') {
        patchEdit(shotId, { subtitle: r.text, subtitle_lock: false })
      } else {
        const cur = editOf(shotId)
        patchEdit(shotId, cur.subtitle_lock
          ? { narration: r.text }
          : { narration: r.text, subtitle: fitSubtitle(r.text, shotId) })
      }
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
    } finally {
      setAiBusy('')
    }
  }

  const ttsOne = async (shotId: string) => {
    setAiBusy(`${shotId}:tts`)
    const text = editOf(shotId).narration.trim()
    if (!text) { setError('先写旁白文案，再点配音'); return }
    try {
      const audio = await api.aiTts({ text, shot_id: shotId, voice: editOf(shotId).tts_voice || undefined })
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
    } finally {
      setAiBusy('')
    }
  }

  const startPreview = async () => {
    if (!ordered.length) return
    setPreviewBusy(true)
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
        volume_db: Number(editOf(s.id).volume_db) || 0,
        speed: Number(editOf(s.id).speed) || 1,
        fit: editOf(s.id).fit || '',
        burned_subtitle: isBurned(s.id),
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
      setPreviewBusy(false)
    }
  }

  const exportRender = async (burnedOverride?: boolean) => {
    if (!ordered.length) return
    setExportBusy(true)
    setError('')
    const res = RESOLUTIONS.find((r) => r.key === resKey) || RESOLUTIONS[1]
    try {
      await api.createRender(projectId, ordered.map((s) => s.id), {
        width: res.width, height: res.height, fps, fit: fitMode,
        transition: { type: transType, duration: transDur },
        title: { enabled: titleOn, text: titleText, duration: titleDur, bg: titleBg, bg_asset: titleImage },
        tail: { enabled: tailOn, text: tailText, duration: tailDur, bg: tailBg, bg_asset: tailImage },
        bgm: { duck: duckBgm, duck_db: -14 },
        bgm_tracks: bgmTracks.filter((t) => t.asset_id).map((t) => ({
          id: t.id, asset_id: t.asset_id, volume_db: t.volume_db,
          start: t.start, end: t.end, fade_in: t.fade_in, fade_out: t.fade_out, loop: t.loop,
        })),
        subtitles: { enabled: subsEnabled, autofit: subAutoFit, language: subLang,
                     style: { size: subSize, margin_v: subMargin } },
        loudness: { enabled: loudness },
      }, ordered.map((s) => ({
        shot_id: s.id,
        in_point: Number(editOf(s.id).in_point) || 0,
        out_point: editOf(s.id).out_point ? Number(editOf(s.id).out_point) : undefined,
        subtitle: editOf(s.id).subtitle || s.title || '',
        voice_asset: editOf(s.id).voice_asset || '',
        volume_db: Number(editOf(s.id).volume_db) || 0,
        speed: Number(editOf(s.id).speed) || 1,
        fit: editOf(s.id).fit || '',
        burned_subtitle: burnedOverride ?? isBurned(s.id),
      })))
      onGoRenders()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setExportBusy(false)
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>剪辑</h1>
          <p>选镜头、剪首尾、写字幕、配 BGM；改动自动保存，下次回来接着改。</p>
        </div>
        <div className="head-controls">
          <label className="inline-field">
            <span>项目</span>
            <select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
              {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
          <label className="inline-field">
            <span>视频自带字幕</span>
            <input type="checkbox" checked={burnedDefault}
                   title="项目默认：勾上后所有镜头默认不再生成/烧录字幕"
                   onChange={(e) => setBurnedDefault(e.target.checked)} />
          </label>
          <button className="primary" onClick={() => setAiOpen(true)} disabled={aiRunning}>
            {aiRunning ? <><span className="spin" /> 生成中</> : 'AI 剪辑'}
          </button>
          <button disabled={previewBusy || !ordered.length} onClick={() => void startPreview()}>
            {previewBusy || (previewJob && ['queued', 'preparing', 'rendering'].includes(previewJob.status))
              ? <><span className="spin" /> 预览中</> : '预览（480p）'}
          </button>
          <button disabled={exportBusy || !ordered.length} onClick={() => void exportRender()}>
            {exportBusy ? <><span className="spin" /> 提交中</> : '导出成片'}
          </button>
          {savedAt && <span className="meta">已自动保存 {savedAt}</span>}
        </div>
      </div>

      <input ref={voiceInput} type="file" hidden accept="audio/*"
             onChange={(e) => void uploadVoice(e.target.files)} />

      {aiOpen && (
        <div className="picker-overlay" onClick={() => !aiRunning && setAiOpen(false)}>
          <div className="picker" style={{ width: 460 }} onClick={(e) => e.stopPropagation()}>
            <div className="picker-head">
              <b>AI 剪辑</b>
              <button className="ghost tiny" onClick={() => setAiOpen(false)}>关闭</button>
            </div>
            <div className="ai-modal-body">
            <div className="meta">按每个镜头的「有旁白 / 有口播」设置分别生成。</div>
            <div className="field"><label><span>生成内容</span></label>
              <select value={aiKind} onChange={(e) => setAiKind(e.target.value as typeof aiKind)}>
                <option value="both">字幕 + 旁白</option>
                <option value="subtitle">只生成字幕</option>
                <option value="narration">只生成旁白</option>
                <option value="merge">仅合并（不生成文案，直接导出）</option>
              </select>
            </div>
            {aiKind === 'merge' ? (
              <>
                <div className="meta">
                  仅做裁剪、拼接、转场和音频混合，不生成字幕/旁白。
                </div>
                <label className="check">
                  <input type="checkbox" checked={mergeBurned}
                         onChange={(e) => setMergeBurned(e.target.checked)} />
                  视频已自带字幕（不重复烧录）
                </label>
              </>
            ) : (
            <>
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
              <select value={subLang} onChange={(e) => changeLang(e.target.value as 'zh' | 'bilingual')}>
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
              {aiTtsOn && (aiKind === 'narration' || aiKind === 'both') && (
                <label className="check" style={{ margin: 0 }}
                       title="旁白比镜头长时，给画面提速对齐（只加速，最多 1.25x）">
                  <input type="checkbox" checked={aiAutoSpeed} onChange={(e) => setAiAutoSpeed(e.target.checked)} />
                  自动匹配镜头时长
                </label>
              )}
              <label className="check" style={{ margin: 0 }}>
                <input type="checkbox" checked={aiTitles} onChange={(e) => setAiTitles(e.target.checked)} />
                同时生成片头/片尾文案（全片一键）
              </label>
            </div>
            <div className="field">
              <label><span>背景音乐（可选）</span></label>
              <select value={aiBgmId} onChange={(e) => setAiBgmId(e.target.value)}>
                <option value="">不自动配置 BGM</option>
                {audios.map((a) => (
                  <option key={a.id} value={a.id}>{audioLabel(a)}</option>
                ))}
              </select>
              {aiBgmId && (
                <p className="hint" style={{ marginTop: 4 }}>
                  会自动写入一条铺满正片的 BGM（淡入 1s、淡出 2s、循环），
                  音量按有无旁白取 -18 / -12dB，之后可在右侧微调。
                </p>
              )}
            </div>
            </>
            )}
            {aiKind !== 'merge' && (
            <div className="row" style={{ alignItems: 'center' }}>
              <label className="check" style={{ margin: 0 }}>
                <input type="checkbox" checked={aiFrames > 0}
                       onChange={(e) => { setAiFrames(e.target.checked ? 3 : 0); setAiFrameGroups([]) }} />
                附带视频截图给 AI（多模态）
              </label>
              {aiFrames > 0 && (
                <>
                  <input type="range" min={1} max={6} value={aiFrames}
                         onChange={(e) => { setAiFrames(Number(e.target.value)); setAiFrameGroups([]) }} />
                  <span className="meta">{aiFrames} 张</span>
                  <button className="ghost tiny" disabled={framesBusy} onClick={() => void loadFrames()}>
                    {framesBusy ? <><span className="spin" /> 截图中</> : '预览截图'}
                  </button>
                </>
              )}
            </div>
            )}
            {aiKind !== 'merge' && aiFrameGroups.length > 0 && (
              <div className="frame-groups">
                {aiFrameGroups.map((group) => (
                  <div key={group.shotId} className="frame-group">
                    <div className="frame-group-head">
                      <b>{group.title}</b>
                      <span className="meta">{group.urls.length} 帧</span>
                    </div>
                    <div className="frame-strip">
                      {group.urls.map((url) => <img key={url} src={url} alt={group.title} />)}
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className="row" style={{ alignItems: 'center' }}>
              <button className="ghost tiny" disabled={rhythmBusy} onClick={() => void runRhythm()}>
                {rhythmBusy ? <><span className="spin" /> 检查中</> : '节奏检查'}
              </button>
              {rhythm && <span className="meta">{rhythm.summary}</span>}
            </div>
            {rhythm && rhythm.bgm_tips && rhythm.bgm_tips.length > 0 && (
              <div className="ai-rows">
                {rhythm.bgm_tips.map((tip, index) => (
                  <div key={index} className={`ai-row ${tip.level === 'warn' ? 'error' : ''}`}>
                    <span className="ai-dot" />
                    <span>{tip.text}</span>
                  </div>
                ))}
              </div>
            )}
            {rhythm && rhythm.items.some((i) => i.level !== 'ok') && (
              <div className="ai-rows">
                {rhythm.items.filter((i) => i.level !== 'ok').map((item) => (
                  <div key={item.shot_id} className="ai-row error">
                    <span className="ai-dot" />
                    <b>{item.title || item.shot_id}</b>
                    <span>{item.duration}s · {item.advice}</span>
                  </div>
                ))}
              </div>
            )}
            <div style={{ display: 'flex' }}>
              <button className="ghost tiny" onClick={() => setShowPrompt((v) => !v)}>
                {showPrompt ? '收起提示词预览' : '查看提示词预览'}
              </button>
            </div>
            {showPrompt && <pre className="prompt-preview">{promptPreview()}</pre>}

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
            </div>
            <div className="row-actions">
              <button className="primary" disabled={aiRunning || !ordered.length} onClick={() => void runAI()}>
                {aiRunning ? '处理中…' : aiKind === 'merge' ? '合并导出' : `开始（${ordered.length} 镜）`}
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
        <div className="ed-col">
        <div className="panel panel-shots">
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
                <span>
                  <em className={`mode-dot ${modeOf(item.shot_id)}`} />
                  {item.title}
                </span>
                <i>{modeLabel(modeOf(item.shot_id))} · {item.duration.toFixed(1)}s</i>
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
                    <span className={`mode-badge ${modeOf(shot.id)}`}>{modeLabel(modeOf(shot.id))}</span>
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
                  {on && activeShot === shot.id && (
                    <div className="render-shot-edit"
                         onClick={(e) => { e.stopPropagation(); setActiveShot(shot.id) }}
                         onFocusCapture={() => setActiveShot(shot.id)}>
                      <div className="shot-section">
                        <div className="shot-section-head">基础</div>
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
                          <label>
                            速度
                            <select value={edit.speed}
                                    onChange={(e) => patchEdit(shot.id, { speed: e.target.value })}>
                              <option value="1">1.0x</option>
                              <option value="0.6">0.6x 慢</option>
                              <option value="0.8">0.8x</option>
                              <option value="1.2">1.2x</option>
                              <option value="1.5">1.5x 快</option>
                              <option value="2">2.0x</option>
                            </select>
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
                          <label>
                            自带字幕
                            <select value={edit.burned_mode}
                                    onChange={(e) => patchEdit(shot.id, { burned_mode: e.target.value })}>
                              <option value="inherit">跟随全局</option>
                              <option value="on">是</option>
                              <option value="off">否</option>
                            </select>
                          </label>
                        </div>
                      </div>

                      <div className="shot-section">
                        <div className="shot-section-head">字幕</div>
                        <div className="shot-row">
                          <label className="grow">
                            文案
                            <div className="voice-pick">
                              <input className="grow" placeholder={shot.title || '这一镜的字幕'}
                                     value={edit.subtitle}
                                     onChange={(e) => patchEdit(shot.id, { subtitle: e.target.value })} />
                              {isBurned(shot.id) && <span className="badge">视频自带字幕</span>}
                              {edit.narration_on && !edit.subtitle_lock && edit.narration.trim() && (
                                <span className="badge">
                                  {edit.subtitle !== edit.narration && subAutoFit ? '已按阅读速度压缩' : '跟随旁白'}
                                </span>
                              )}
                              {edit.narration_on && !edit.narration.trim() && (
                                <span className="badge warn">无旁白文案</span>
                              )}
                              {edit.narration_on && edit.subtitle_lock && (
                                <button className="ghost tiny"
                                        title="重新让字幕和旁白保持一致"
                                        onClick={() => patchEdit(shot.id, { subtitle: fitSubtitle(edit.narration, shot.id), subtitle_lock: false, burned_mode: 'inherit' })}>
                                  恢复跟随
                                </button>
                              )}
                              {!edit.narration_on && edit.lip_on && (
                                <button className="ghost tiny" disabled={aiBusy === `${shot.id}:subtitle`}
                                        title="检测人声并转写"
                                        onClick={() => void aiOne(shot.id, 'subtitle')}>
                                  {aiBusy === `${shot.id}:subtitle` ? <><span className="spin" /> 转写中</> : '转写'}
                                </button>
                              )}
                            </div>
                          </label>
                        </div>
                      </div>

                      <div className="shot-section">
                        <div className="shot-section-head">旁白 / 口播</div>
                        <div className="shot-row">
                          <div className="mode-toggles">
                            <label className="check" style={{ margin: 0 }}>
                              <input type="checkbox" checked={edit.narration_on}
                                     onChange={(e) => setNarration(shot.id, e.target.checked)} />
                              有旁白
                            </label>
                            <label className="check" style={{ margin: 0 }}>
                              <input type="checkbox" checked={edit.lip_on}
                                     onChange={(e) => setLip(shot.id, e.target.checked)} />
                              有口播
                            </label>
                          </div>
                        </div>
                        {(edit.narration_on || edit.lip_on) && (
                          <div className="shot-row">
                            {edit.narration_on && (
                              <label>
                                音色
                                <select value={edit.tts_voice}
                                        onChange={(e) => patchEdit(shot.id, { tts_voice: e.target.value })}>
                                  <option value="">跟随默认</option>
                                  {voiceOptions.map((v) => (
                                    <option key={v.id} value={v.id}>{v.name || v.id}</option>
                                  ))}
                                </select>
                              </label>
                            )}
                            {edit.lip_on && (
                              <label>
                                原声音量
                                <input type="number" step={1} value={edit.volume_db}
                                       onChange={(e) => patchEdit(shot.id, { volume_db: e.target.value })} />
                              </label>
                            )}
                          </div>
                        )}

                        {edit.narration_on ? (
                          <>
                            <div className="shot-row">
                              <label className="grow">
                                文案
                                <input placeholder="旁白文本（配音用）"
                                       value={edit.narration}
                                       onChange={(e) => setNarrationText(shot.id, e.target.value)} />
                              </label>
                            </div>
                            <div className="shot-row">
                              <label className="grow">
                                音频
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
                                  <button className="ghost tiny" disabled={aiBusy === `${shot.id}:narration`}
                                          onClick={() => void aiOne(shot.id, 'narration')}>
                                    {aiBusy === `${shot.id}:narration` ? <><span className="spin" /> 生成中</> : 'AI 写'}
                                  </button>
                                  <button className="ghost tiny" disabled={!edit.narration.trim() || aiBusy === `${shot.id}:tts`}
                                          title={edit.narration.trim() ? '合成配音' : '先写旁白文案'}
                                          onClick={() => void ttsOne(shot.id)}>
                                    {aiBusy === `${shot.id}:tts` ? <><span className="spin" /> 配音中</> : '配音'}
                                  </button>
                                  <button className="ghost tiny" disabled={!edit.voice_asset}
                                          onClick={() => void playVoice(shot.id)}>
                                    {playingVoice === shot.id ? '停止' : '试听'}
                                  </button>
                                  {edit.narration.trim() && !edit.voice_asset && <span className="badge warn">未配音</span>}
                                  {!edit.narration.trim() && edit.voice_asset && <span className="badge">仅音频</span>}
                                </div>
                              </label>
                            </div>
                          </>
                        ) : (
                          <div className="meta">
                            {edit.lip_on
                              ? '没有旁白：字幕来自语音转写，保留原声'
                              : '既没有旁白也没有口播：不加字幕'}
                          </div>
                        )}

                        {edit.narration_on && edit.lip_on && (
                          <div className="meta" style={{ color: '#facc15' }}>
                            同时有旁白和口播：字幕跟随旁白，旁白会叠在原声上，建议把原声音量调到 -10dB 左右
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
            {!shots.length && <div className="empty">这个项目还没有镜头，先去项目页加一镜。</div>}
          </div>
        </div>

        <div className="panel panel-preview">
          <h2>
            <span>预览</span>
            <span className="meta">{activeShot ? (shots.find((s) => s.id === activeShot)?.title || '') : '选择镜头'}</span>
          </h2>
          {previewJob && ['queued', 'preparing', 'rendering'].includes(previewJob.status) ? (
            <div className="preview-empty">
              <span className="spin" /> 正在生成整片预览，完成后才能播放
            </div>
          ) : (previewJob?.status === 'succeeded' && previewJob.url) || shotPreview.url ? (
            <div className="canvas-box" style={{
              aspectRatio: `${(RESOLUTIONS.find((r) => r.key === resKey) || RESOLUTIONS[1]).width} / ${
                (RESOLUTIONS.find((r) => r.key === resKey) || RESOLUTIONS[1]).height}`,
              ['--ar' as string]: String(
                (RESOLUTIONS.find((r) => r.key === resKey) || RESOLUTIONS[1]).width /
                (RESOLUTIONS.find((r) => r.key === resKey) || RESOLUTIONS[1]).height,
              ),
            }}>
              <video key={previewJob?.url || shotPreview.url} className="preview-video" ref={previewVideoRef}
                     src={previewJob?.status === 'succeeded' && previewJob.url ? previewJob.url : shotPreview.url}
                     onTimeUpdate={(e) => setPlayhead(filmTimeOf(e.currentTarget.currentTime))}
                     onSeeked={(e) => setPlayhead(filmTimeOf(e.currentTarget.currentTime))}
                     onEnded={() => {
                       if (usingFilmPreview) {
                         setPlayhead(filmDuration)
                         return
                       }
                       const index = timeline.findIndex((i) => i.shot_id === activeShot)
                       const item = timeline[index]
                       if (!item) return
                       setPlayhead(index === timeline.length - 1 ? filmDuration : item.end)
                     }}
                     controls />
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
        </div>

        <div className="panel panel-timeline">
          <h2>
            <span>音乐轨道</span>
            <span className="meta">拖拽色块调整起止 · 点刻度跳转预览</span>
          </h2>
          <BgmTimeline
            duration={filmDuration}
            shots={timeline.map((t) => ({ shot_id: t.shot_id, title: t.title, duration: t.duration, start: t.start }))}
            tracks={bgmTracks}
            narration={narrationClips}
            onSelectShot={setActiveShot}
            activeId={activeTrackId}
            titles={Object.fromEntries(audios.map((a) => [a.id, audioLabel(a)]))}
            urls={Object.fromEntries(audios.map((a) => [a.id, a.url || `/media/files/${a.path}`]))}
            currentTime={playhead}
            onSelect={setActiveTrackId}
            onChange={updateTrack}
            onSeek={seekFilm}
          />
        </div>
        </div>

        <div className="panel panel-side">
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
              <button className="ghost tiny" disabled={titleBusy === 'title'} onClick={() => void aiTitle('title')}>
                {titleBusy === 'title' ? <><span className="spin" /> 起名中</> : 'AI 起名'}
              </button>
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
              <button className="ghost tiny" disabled={titleBusy === 'tail'} onClick={() => void aiTitle('tail')}>
                {titleBusy === 'tail' ? <><span className="spin" /> 生成中</> : 'AI 起名'}
              </button>
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
          {bgmTracks.length === 0 && (
            <p className="hint">还没有音乐。可以加多条：铺底、高潮、结尾各一条；在左侧「音乐轨道」里拖拽调整区间。</p>
          )}
          {bgmTracks.map((track, index) => (
            <div key={track.id} className="bgm-track">
              <div className="bgm-track-head">
                <span className="meta">音乐 {index + 1}</span>
                <button className="ghost tiny"
                        onClick={() => setBgmTracks((prev) => prev.filter((t) => t.id !== track.id))}>
                  删除
                </button>
              </div>
              <select className="grow" value={track.asset_id}
                      onChange={(e) => updateTrack(track.id, { asset_id: e.target.value })}>
                <option value="">选择音频</option>
                {audios.map((a) => (
                  <option key={a.id} value={a.id}>{audioLabel(a)}</option>
                ))}
              </select>
              <div className="row">
                <label className="inline-field">
                  <span>音量</span>
                  <input type="number" step={1} value={track.volume_db}
                         onChange={(e) => updateTrack(track.id, { volume_db: Number(e.target.value) })} />
                  <span className="meta">dB</span>
                </label>
                <label className="inline-field">
                  <span>起点</span>
                  <input type="number" step={0.5} min={0} value={track.start}
                         onChange={(e) => updateTrack(track.id, { start: Number(e.target.value) })} />
                  <span className="meta">s</span>
                </label>
                <label className="inline-field">
                  <span>终点</span>
                  <input type="number" step={0.5} min={0} placeholder="到结尾"
                         value={track.end ?? ''}
                         onChange={(e) => updateTrack(track.id, { end: e.target.value === '' ? null : Number(e.target.value) })} />
                  <span className="meta">s</span>
                </label>
              </div>
              <div className="row">
                <label className="inline-field">
                  <span>淡入</span>
                  <input type="number" step={0.1} min={0} value={track.fade_in}
                         onChange={(e) => updateTrack(track.id, { fade_in: Number(e.target.value) })} />
                </label>
                <label className="inline-field">
                  <span>淡出</span>
                  <input type="number" step={0.1} min={0} value={track.fade_out}
                         onChange={(e) => updateTrack(track.id, { fade_out: Number(e.target.value) })} />
                </label>
                <label className="check" style={{ margin: 0 }}>
                  <input type="checkbox" checked={track.loop}
                         onChange={(e) => updateTrack(track.id, { loop: e.target.checked })} />
                  循环铺满区间
                </label>
              </div>
            </div>
          ))}
          <div className="row">
            <button className="ghost tiny" disabled={bgmTracks.length >= 4}
                    onClick={() => setBgmTracks((prev) => [...prev, {
                      id: `t${Date.now().toString(36)}`,
                      asset_id: '', volume_db: -14, start: 0, end: null,
                      fade_in: 0.5, fade_out: 0.5, loop: true,
                    }])}>
              + 添加音乐
            </button>
            <span className="meta">最多 4 条 · 起点相对正片（片头之后）</span>
          </div>
          <label className="check">
            <input type="checkbox" checked={duckBgm} onChange={(e) => setDuckBgm(e.target.checked)} />
            旁白出现时自动压低 BGM
          </label>

          <h3>字幕</h3>
          <label className="check">
            <input type="checkbox" checked={subsEnabled} onChange={(e) => setSubsEnabled(e.target.checked)} />
            烧录到画面
          </label>
          <div className="row">
            <label className="inline-field">
              <span>字幕语言</span>
              <select value={subLang} onChange={(e) => changeLang(e.target.value as 'zh' | 'bilingual')}>
                <option value="zh">中文</option>
                <option value="bilingual">中英双语</option>
              </select>
            </label>
          </div>
          <p className="hint" style={{ marginTop: 4 }}>
            {subLang === 'bilingual'
              ? 'AI 生成字幕时输出中英两行；手动改写的字幕请自己写成两行。'
              : 'AI 生成字幕时输出中文；手动改写的字幕按你写的内容原样烧录。'}
          </p>
          <label className="check">
            <input type="checkbox" checked={subAutoFit} onChange={(e) => setSubAutoFit(e.target.checked)} />
            旁白过长时自动压缩字幕（每秒 4.5 字）
          </label>

          {subsEnabled && (
            <div className="row">
              <label className="slider grow">
                字号 {subSize}
                {subLang === 'bilingual' && <span className="meta">（双语建议 ≤44）</span>}
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


        </div>

      </div>
    </div>
  )
}
