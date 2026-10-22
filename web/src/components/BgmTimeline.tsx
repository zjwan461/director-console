import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'

export interface BgmTrackView {
  id: string
  asset_id: string
  volume_db: number
  start: number
  end: number | null
  fade_in: number
  fade_out: number
  loop: boolean
}

interface ShotBlock {
  shot_id: string
  title: string
  duration: number
}

export interface NarrationClip {
  shot_id: string
  title: string
  start: number
  end: number
  asset_id: string
  audio_duration: number
  pending?: boolean
  has_text?: boolean
}

interface Props {
  duration: number
  shots: ShotBlock[]
  narration?: NarrationClip[]
  onSelectShot?: (shotId: string) => void
  tracks: BgmTrackView[]
  activeId: string
  titles: Record<string, string>
  urls?: Record<string, string>
  currentTime?: number
  onSelect: (id: string) => void
  onChange: (id: string, patch: Partial<BgmTrackView>) => void
  onSeek?: (seconds: number) => void
}

const COLORS = ['#6d8bff', '#55c2a0', '#e2a04a', '#c46bd6']
const ZOOMS = [1, 2, 4, 8]

type DragMode = 'move' | 'start' | 'end' | 'playhead'

export default function BgmTimeline({
  duration, shots, tracks, narration = [], onSelectShot, activeId, titles, urls = {}, currentTime = 0,
  onSelect, onChange, onSeek,
}: Props) {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const railRef = useRef<HTMLDivElement | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [zoom, setZoom] = useState(1)
  const [peaks, setPeaks] = useState<Record<string, number[]>>({})
  const [audition, setAudition] = useState('')
  const [drag, setDrag] = useState<{
    id: string; mode: DragMode; x0: number; start0: number; end0: number; endOpen: boolean; width: number; moved: boolean
  } | null>(null)

  const total = Math.max(duration, 1)

  // 镜头切点，拖动时吸附
  const cutPoints = useMemo(() => {
    const points: number[] = [0, total]
    let acc = 0
    for (const shot of shots) {
      acc += shot.duration
      points.push(acc)
    }
    return points
  }, [shots, total])

  useEffect(() => {
    let alive = true
    const ids = [...tracks.map((t) => t.asset_id), ...narration.map((n) => n.asset_id)]
    for (const id of ids) {
      if (!id || peaks[id]) continue
      api.assetWaveform(id).then((res) => {
        if (alive) setPeaks((prev) => ({ ...prev, [id]: res.peaks }))
      }).catch(() => undefined)
    }
    return () => { alive = false }
  }, [tracks, narration, peaks])

  useEffect(() => {
    if (!drag) return
    const move = (event: PointerEvent) => {
      const dx = event.clientX - drag.x0
      if (Math.abs(dx) > 3) setDrag((prev) => (prev && !prev.moved ? { ...prev, moved: true } : prev))
      const seconds = (dx / drag.width) * total
      if (drag.mode === 'playhead') {
        onSeek?.(clampTo(drag.start0 + seconds))
        return
      }
      if (drag.mode === 'move') {
        const raw = Math.max(0, Math.min(drag.start0 + seconds, total - 0.5))
        const nextStart = snap(raw, cutPoints, total, drag.width)
        const delta = nextStart - drag.start0
        onChange(drag.id, {
          start: round(Math.max(0, nextStart)),
          end: drag.endOpen ? null : round(Math.min(drag.end0 + delta, total)),
        })
      } else if (drag.mode === 'start') {
        const raw = Math.max(0, Math.min(drag.start0 + seconds, drag.end0 - 0.5))
        onChange(drag.id, { start: round(Math.max(0, snap(raw, cutPoints, total, drag.width))) })
      } else {
        const raw = Math.max(drag.start0 + 0.5, Math.min(drag.end0 + seconds, total))
        const snapped = snap(raw, cutPoints, total, drag.width)
        onChange(drag.id, { end: snapped >= total - 0.05 ? null : round(snapped) })
      }
    }
    const up = () => setDrag(null)
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
  }, [drag, onChange, onSeek, total, cutPoints])

  const beginDrag = (event: React.PointerEvent, track: BgmTrackView, mode: DragMode) => {
    event.stopPropagation()
    const width = railRef.current?.clientWidth || 1
    onSelect(track.id)
    setDrag({ id: track.id, mode, x0: event.clientX, start0: track.start,
      end0: track.end ?? total, endOpen: track.end === null, width, moved: false })
  }

  const beginPlayhead = (event: React.PointerEvent) => {
    event.stopPropagation()
    const width = railRef.current?.clientWidth || 1
    setDrag({ id: 'playhead', mode: 'playhead', x0: event.clientX,
      start0: currentTime, end0: total, endOpen: true, width, moved: false })
  }

  const seekAt = (event: React.MouseEvent) => {
    if (!onSeek) return
    const rect = railRef.current?.getBoundingClientRect()
    if (!rect) return
    const ratio = Math.max(0, Math.min((event.clientX - rect.left) / rect.width, 1))
    onSeek(ratio * total)
  }

  const auditionTrack = async (track: BgmTrackView) => {
    const url = urls[track.asset_id]
    if (!url) return
    if (audition === track.id) {
      audioRef.current?.pause()
      setAudition('')
      return
    }
    const audio = audioRef.current
    if (!audio) return
    audio.src = url
    audio.currentTime = track.start
    audio.volume = Math.max(0, Math.min(1, Math.pow(10, track.volume_db / 20)))
    try {
      await audio.play()
      setAudition(track.id)
    } catch {
      setAudition('')
    }
  }

  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return
    const stop = () => setAudition('')
    audio.addEventListener('ended', stop)
    return () => audio.removeEventListener('ended', stop)
  }, [])

  // 试听时到了区间末尾自动停
  useEffect(() => {
    if (!audition) return
    const timer = window.setInterval(() => {
      const track = tracks.find((t) => t.id === audition)
      const audio = audioRef.current
      if (!track || !audio) return
      const end = track.end ?? total
      if (!audio.paused && audio.currentTime >= end) {
        audio.pause()
        setAudition('')
      }
    }, 200)
    return () => window.clearInterval(timer)
  }, [audition, tracks, total])

  const ticks = buildTicks(total, zoom)

  return (
    <div className="tl">
      <div className="tl-head">
        <span className="tl-label">时间轴</span>
        <div className="tl-tools">
          <span className="meta">{formatTime(currentTime)} / {formatTime(total)}</span>
          <button className="ghost tiny" onClick={() => setZoom((z) => ZOOMS[Math.max(0, ZOOMS.indexOf(z) - 1)] ?? 1)}
                  disabled={zoom === 1}>－</button>
          <span className="meta">{zoom}x</span>
          <button className="ghost tiny" onClick={() => setZoom((z) => ZOOMS[Math.min(ZOOMS.length - 1, ZOOMS.indexOf(z) + 1)] ?? z)}
                  disabled={zoom === ZOOMS[ZOOMS.length - 1]}>＋</button>
        </div>
      </div>

      <div className="tl-body" ref={scrollRef}>
        <div className="tl-gutter">
          <div className="tl-gutter-row tl-gutter-ruler">时</div>
          <div className="tl-gutter-row">画面</div>
          {narration.some((clip) => clip.asset_id) && <div className="tl-gutter-row">旁白</div>}
          {tracks.map((track) => (
            <div key={track.id} className="tl-gutter-row">音乐</div>
          ))}
        </div>

        <div className="tl-scroll">
          <div className="tl-rail" ref={railRef} style={{ width: `${zoom * 100}%` }}>
            <div className="tl-ruler" onClick={seekAt}>
              {ticks.map((tick) => {
                const pct = (tick / total) * 100
                const shift = pct <= 0.5 ? '0' : pct >= 99.5 ? '-100%' : '-50%'
                return (
                  <span key={tick} className="tl-tick" style={{ left: `${pct}%`, transform: `translateX(${shift})` }}>
                    {formatTime(tick)}
                  </span>
                )
              })}
            </div>

            <div className="tl-shots" onClick={seekAt}>
              {shots.map((shot, index) => {
                const left = (shots.slice(0, index).reduce((sum, s) => sum + s.duration, 0) / total) * 100
                const width = (shot.duration / total) * 100
                return (
                  <div key={shot.shot_id} className="tl-shot" style={{ left: `${left}%`, width: `${width}%` }}
                       title={`${shot.title} ${shot.duration.toFixed(1)}s`}>
                    <span>{shot.title}</span>
                  </div>
                )
              })}
            </div>

            {narration.some((clip) => clip.asset_id || clip.pending) && (
              <div className="tl-track tl-track-narration">
                {narration.filter((clip) => clip.asset_id || clip.pending).map((clip) => {
                  if (!clip.asset_id) {
                    const warnLeft = (clip.start / total) * 100
                    const warnWidth = Math.max(((clip.end - clip.start) / total) * 100, 1)
                    return (
                      <div key={clip.shot_id}
                           className="tl-clip tl-clip-pending"
                           style={{ left: `${warnLeft}%`, width: `${warnWidth}%` }}
                           onClick={(event) => { event.stopPropagation(); onSelectShot?.(clip.shot_id) }}
                           title={`${clip.title}：开了旁白但还没配音${clip.has_text ? '（文案已写）' : '（也没写文案）'}`}>
                        <span className="tl-pending-badge">⚠</span>
                        <span className="tl-clip-label">
                          {clip.has_text ? '待配音' : '待写文案'}
                        </span>
                      </div>
                    )
                  }
                  const left = (clip.start / total) * 100
                  const width = Math.max(((clip.end - clip.start) / total) * 100, 1)
                  const bars = peaks[clip.asset_id] || []
                  return (
                    <div key={clip.shot_id}
                         className="tl-clip tl-clip-narration"
                         style={{ left: `${left}%`, width: `${width}%`, borderColor: '#9a7bf0', background: '#9a7bf022' }}
                         onClick={(event) => { event.stopPropagation(); onSelectShot?.(clip.shot_id) }}
                         title={`${clip.title} · 旁白 ${clip.audio_duration.toFixed(1)}s`}>
                      <div className="tl-wave">
                        {bars.map((peak, i) => (
                          <i key={i} style={{ height: `${Math.max(peak * 100, 6)}%`, background: '#b39cf5' }} />
                        ))}
                      </div>
                      <span className="tl-clip-label">
                        {clip.asset_id ? `旁白 · ${clip.title}` : '无旁白'}
                      </span>
                    </div>
                  )
                })}
              </div>
            )}

            {tracks.map((track, index) => {
              const start = Math.min(track.start, total)
              const end = Math.min(track.end ?? total, total)
              const left = (start / total) * 100
              const width = Math.max(((end - start) / total) * 100, 1.5)
              const color = COLORS[index % COLORS.length]
              const bars = peaks[track.asset_id] || []
              return (
                <div key={track.id}
                     className={`tl-track ${activeId === track.id ? 'active' : ''}`}
                     onPointerDown={(event) => beginDrag(event, track, 'move')}
                     onDoubleClick={() => void auditionTrack(track)}>
                  <div className="tl-clip"
                       style={{ left: `${left}%`, width: `${width}%`, background: `${color}22`, borderColor: color }}>
                    <span className="tl-handle left" onPointerDown={(event) => beginDrag(event, track, 'start')} />
                    <div className="tl-wave">
                      {bars.map((peak, i) => (
                        <i key={i} style={{ height: `${Math.max(peak * 100, 6)}%`, background: color }} />
                      ))}
                    </div>
                    <span className="tl-clip-label">
                      {audition === track.id ? '▶ ' : ''}{titles[track.asset_id] || '音乐'}
                    </span>
                    <span className="tl-handle right" onPointerDown={(event) => beginDrag(event, track, 'end')} />
                  </div>
                </div>
              )
            })}
            {!tracks.length && <div className="tl-empty">添加音乐后会在这里显示</div>}

            <div className="tl-playhead" style={{ left: `${(Math.min(currentTime, total) / total) * 100}%` }}
                 onPointerDown={beginPlayhead}>
              <span className="tl-playhead-grip" />
            </div>
          </div>
        </div>
      </div>
      <audio ref={audioRef} hidden />
    </div>
  )
}

function clampTo(value: number) {
  return Math.max(0, value)
}

/** 吸附到最近的镜头切点（阈值按像素换算成秒） */
function snap(value: number, points: number[], total: number, width: number) {
  const threshold = (8 / Math.max(width, 1)) * total
  let best = value
  let bestDist = threshold
  for (const point of points) {
    const dist = Math.abs(point - value)
    if (dist < bestDist) {
      best = point
      bestDist = dist
    }
  }
  return best
}

function round(value: number) {
  return Math.round(value * 20) / 20
}

function formatTime(seconds: number) {
  const s = Math.max(0, seconds)
  const m = Math.floor(s / 60)
  const rest = Math.floor(s % 60)
  return `${m}:${String(rest).padStart(2, '0')}`
}

function buildTicks(total: number, zoom: number) {
  const base = total > 60 ? 15 : total > 30 ? 10 : total > 12 ? 5 : 2
  const step = Math.max(0.5, base / Math.max(zoom, 1))
  const ticks: number[] = []
  for (let t = 0; t < total - 0.05; t += step) ticks.push(Math.round(t * 10) / 10)
  ticks.push(Math.round(total * 10) / 10)
  return ticks
}
