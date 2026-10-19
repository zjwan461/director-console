import { useEffect, useMemo, useState } from 'react'
import { api, timeAgo } from '../api'
import type { Render, Shot } from '../types'

const RESOLUTIONS = [
  { key: '1280x720', label: '横屏 720p', width: 1280, height: 720 },
  { key: '1920x1080', label: '横屏 1080p', width: 1920, height: 1080 },
  { key: '720x1280', label: '竖屏 720p', width: 720, height: 1280 },
  { key: '1080x1920', label: '竖屏 1080p', width: 1080, height: 1920 },
]

interface Props {
  projectId: string
  shots: Shot[]
}

export default function RenderPanel({ projectId, shots }: Props) {
  const [selected, setSelected] = useState<string[]>([])
  const [resolution, setResolution] = useState(RESOLUTIONS[0].key)
  const [fps, setFps] = useState(24)
  const [renders, setRenders] = useState<Render[]>([])
  const [ffmpeg, setFfmpeg] = useState<{ available: boolean; hint: string; ffmpeg: string } | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.ffmpegStatus().then(setFfmpeg).catch(() => undefined)
  }, [])

  useEffect(() => {
    setSelected(shots.map((s) => s.id))
    if (!projectId) return
    void loadRenders()
  }, [projectId, shots.length])

  useEffect(() => {
    if (!projectId) return
    const pending = renders.some((r) => ['queued', 'preparing', 'rendering'].includes(r.status))
    if (!pending) return
    const timer = setInterval(() => void loadRenders(), 2000)
    return () => clearInterval(timer)
  }, [renders, projectId])

  async function loadRenders() {
    try {
      const res = await api.renders(projectId)
      setRenders(res.items)
    } catch (err) {
      setError(String(err))
    }
  }

  const ordered = useMemo(
    () => selected.map((id) => shots.find((s) => s.id === id)).filter(Boolean) as Shot[],
    [selected, shots],
  )

  const toggle = (id: string) => {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  const move = (id: string, dir: -1 | 1) => {
    setSelected((prev) => {
      const idx = prev.indexOf(id)
      const next = idx + dir
      if (idx < 0 || next < 0 || next >= prev.length) return prev
      const copy = [...prev]
      ;[copy[idx], copy[next]] = [copy[next], copy[idx]]
      return copy
    })
  }

  const create = async () => {
    if (!selected.length) {
      setError('先勾选要合成的镜头')
      return
    }
    const res = RESOLUTIONS.find((r) => r.key === resolution) || RESOLUTIONS[0]
    setError('')
    setBusy(true)
    try {
      await api.createRender(projectId, selected, { width: res.width, height: res.height, fps })
      await loadRenders()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const remove = async (id: string) => {
    if (!window.confirm('删除这份成片？文件也会一起删掉。')) return
    try {
      await api.deleteRender(id)
      await loadRenders()
    } catch (err) {
      setError(String(err))
    }
  }

  return (
    <div className="panel" style={{ marginTop: 14 }}>
      <h2>
        <span>成片导出</span>
        {ffmpeg && (
          <span className={`badge ${ffmpeg.available ? 'ok' : 'err'}`}>
            {ffmpeg.available ? 'ffmpeg 就绪' : '缺少 ffmpeg'}
          </span>
        )}
      </h2>

      {ffmpeg && !ffmpeg.available && (
        <div className="notice err" style={{ marginBottom: 12 }}>{ffmpeg.hint}</div>
      )}

      <div className="field">
        <label><span>镜头顺序（勾选 + 上下调整）</span><span className="meta">已选 {ordered.length} / {shots.length}</span></label>
        <div className="list">
          {shots.map((shot) => {
            const isSelected = selected.includes(shot.id)
            const pos = selected.indexOf(shot.id) + 1
            return (
              <div key={shot.id} className={`list-item ${isSelected ? 'active' : ''}`}>
                <input
                  type="checkbox"
                  checked={isSelected}
                  onChange={() => toggle(shot.id)}
                  style={{ width: 16, height: 16, flex: '0 0 auto' }}
                />
                {pos > 0 && <span className="badge">{pos}</span>}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <b>{shot.title || `镜头 ${shot.idx + 1}`}</b>
                  <div className="meta">{shot.last_frame_url ? '已有产物' : '暂无产物'}</div>
                </div>
                <button className="ghost tiny" disabled={!isSelected} onClick={() => move(shot.id, -1)}>↑</button>
                <button className="ghost tiny" disabled={!isSelected} onClick={() => move(shot.id, 1)}>↓</button>
              </div>
            )
          })}
          {!shots.length && <div className="empty">还没有镜头。</div>}
        </div>
      </div>

      <div className="row" style={{ marginTop: 12 }}>
        <select value={resolution} onChange={(e) => setResolution(e.target.value)}>
          {RESOLUTIONS.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
        </select>
        <select value={fps} onChange={(e) => setFps(Number(e.target.value))}>
          <option value={24}>24 fps</option>
          <option value={30}>30 fps</option>
        </select>
        <button className="primary" disabled={busy || !shots.length} onClick={() => void create()}>
          {busy ? <><span className="spin" /> 提交中</> : '导出成片'}
        </button>
      </div>

      {error && <div className="notice err" style={{ marginTop: 10 }}>{error}</div>}

      {renders.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <h2>历史成片（{renders.length}）</h2>
          <div className="job-list">
            {renders.map((render) => (
              <div className="job" key={render.id}>
                <div className="body">
                  <div className="title">
                    <span className={`badge ${render.status === 'succeeded' ? 'ok' : render.status === 'failed' ? 'err' : ''}`}>
                      {renderStatus(render.status)}
                    </span>
                    <span className="msg">{timeAgo(render.created_at)}</span>
                    <span className="msg">{render.shot_ids.length} 镜</span>
                  </div>
                  <div className="msg">{render.message || '—'}</div>
                  {['queued', 'preparing', 'rendering'].includes(render.status) && (
                    <div className="bar"><i style={{ width: `${Math.round((render.progress || 0) * 100)}%` }} /></div>
                  )}
                  {render.error && <div className="err">{render.error}</div>}
                  <div className="row" style={{ marginTop: 8 }}>
                    {render.output_url && (
                      <>
                        <a href={render.output_url} target="_blank" rel="noreferrer">
                          <button className="ghost">预览</button>
                        </a>
                        <a href={render.output_url} download={render.download_name || true}>
                          <button>下载</button>
                        </a>
                      </>
                    )}
                    <button className="ghost" onClick={() => void remove(render.id)}>删除</button>
                  </div>
                  {render.output_url && (
                    <video src={render.output_url} controls poster={render.cover_url} style={{ width: '100%', maxWidth: 560, borderRadius: 8, marginTop: 8 }} />
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function renderStatus(status: Render['status']): string {
  return {
    queued: '排队中',
    preparing: '准备素材',
    rendering: '合成中',
    succeeded: '已完成',
    failed: '失败',
  }[status] || status
}
