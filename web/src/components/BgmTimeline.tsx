import { useEffect, useRef, useState } from 'react'
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

interface Props {
  duration: number
  shots: ShotBlock[]
  tracks: BgmTrackView[]
  activeId: string
  titles: Record<string, string>
  onSelect: (id: string) => void
  onChange: (id: string, patch: Partial<BgmTrackView>) => void
  onSeek?: (seconds: number) => void
}

const COLORS = ['#6d8bff', '#55c2a0', '#e2a04a', '#c46bd6']

type DragMode = 'move' | 'start' | 'end'

export default function BgmTimeline({
  duration, shots, tracks, activeId, titles, onSelect, onChange, onSeek,
}: Props) {
  const railRef = useRef<HTMLDivElement | null>(null)
  const [drag, setDrag] = useState<{ id: string; mode: DragMode; x0: number; start0: number; end0: number; endOpen: boolean; width: number } | null>(null)
  const [peaks, setPeaks] = useState<Record<string, number[]>>({})

  const total = Math.max(duration, 1)

  // 拉取每条轨道音频的波形（按素材缓存）
  useEffect(() => {
    let alive = true
    for (const track of tracks) {
      if (!track.asset_id || peaks[track.asset_id]) continue
      api.assetWaveform(track.asset_id).then((res) => {
        if (alive) setPeaks((prev) => ({ ...prev, [track.asset_id]: res.peaks }))
      }).catch(() => undefined)
    }
    return () => { alive = false }
  }, [tracks, peaks])

  useEffect(() => {
    if (!drag) return
    const move = (event: PointerEvent) => {
      const dx = event.clientX - drag.x0
      const seconds = (dx / drag.width) * total
      if (drag.mode === 'move') {
        const nextStart = Math.max(0, Math.min(drag.start0 + seconds, total - 0.5))
        const delta = nextStart - drag.start0
        onChange(drag.id, {
          start: round(nextStart),
          // 整段平移时保持长度不变；开放结尾的保持开放
          end: drag.endOpen ? null : round(Math.min(drag.end0 + delta, total)),
        })
      } else if (drag.mode === 'start') {
        const nextStart = Math.max(0, Math.min(drag.start0 + seconds, drag.end0 - 0.5))
        onChange(drag.id, { start: round(nextStart) })
      } else {
        const nextEnd = Math.max(drag.start0 + 0.5, Math.min(drag.end0 + seconds, total))
        onChange(drag.id, { end: nextEnd >= total - 0.05 ? null : round(nextEnd) })
      }
    }
    const up = () => setDrag(null)
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
  }, [drag, onChange, total])

  const beginDrag = (event: React.PointerEvent, track: BgmTrackView, mode: DragMode) => {
    event.stopPropagation()
    const width = railRef.current?.clientWidth || 1
    onSelect(track.id)
    setDrag({
      id: track.id,
      mode,
      x0: event.clientX,
      start0: track.start,
      end0: track.end ?? total,
      endOpen: track.end === null,
      width,
    })
  }

  const seekFromEvent = (event: React.MouseEvent) => {
    if (!onSeek) return
    const rect = railRef.current?.getBoundingClientRect()
    if (!rect) return
    onSeek(Math.max(0, Math.min((event.clientX - rect.left) / rect.width, 1)) * total)
  }

  const ticks = buildTicks(total)

  return (
    <div className="tl">
      <div className="tl-head">
        <span className="tl-label">时间轴</span>
        <span className="meta">{formatTime(total)}</span>
      </div>

      <div className="tl-body">
        <div className="tl-gutter">
          <div className="tl-gutter-row tl-gutter-ruler">时</div>
          <div className="tl-gutter-row">画面</div>
          {tracks.map((track) => (
            <div key={track.id} className="tl-gutter-row">音乐</div>
          ))}
        </div>

        <div className="tl-rail" ref={railRef}>
          <div className="tl-ruler" onClick={seekFromEvent}>
            {ticks.map((tick) => (
              <span key={tick} className="tl-tick" style={{ left: `${(tick / total) * 100}%` }}>
                {formatTime(tick)}
              </span>
            ))}
          </div>

          <div className="tl-shots" onClick={seekFromEvent}>
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
                   onPointerDown={(event) => beginDrag(event, track, 'move')}>
                <div className="tl-clip"
                     style={{ left: `${left}%`, width: `${width}%`, background: `${color}22`, borderColor: color }}>
                  <span className="tl-handle left" onPointerDown={(event) => beginDrag(event, track, 'start')} />
                  <div className="tl-wave">
                    {bars.map((peak, i) => (
                      <i key={i} style={{ height: `${Math.max(peak * 100, 6)}%`, background: color }} />
                    ))}
                  </div>
                  <span className="tl-clip-label">{titles[track.asset_id] || '音乐'}</span>
                  <span className="tl-handle right" onPointerDown={(event) => beginDrag(event, track, 'end')} />
                </div>
              </div>
            )
          })}
          {!tracks.length && <div className="tl-empty">添加音乐后会在这里显示</div>}
        </div>
      </div>
    </div>
  )
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

function buildTicks(total: number) {
  const step = total > 60 ? 15 : total > 30 ? 10 : total > 12 ? 5 : 2
  const ticks: number[] = []
  for (let t = 0; t <= total + 0.001; t += step) ticks.push(Math.round(t * 10) / 10)
  return ticks
}
