import { useCallback, useEffect, useState } from 'react'
import { api, timeAgo } from '../api'
import type { Render } from '../types'

const STATUS_TEXT: Record<string, string> = {
  draft: '草稿',
  queued: '排队中',
  preparing: '准备中',
  rendering: '导出中',
  succeeded: '完成',
  failed: '失败',
}

export default function RendersPanel({ onOpenProject }: { onOpenProject: (projectId: string) => void }) {
  const [items, setItems] = useState<Render[]>([])
  const [filter, setFilter] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')

  const load = useCallback(async () => {
    try {
      const res = await api.allRenders(100, filter || undefined)
      setItems(res.items)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [filter])

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), 4000)
    return () => window.clearInterval(timer)
  }, [load])

  const start = async (id: string) => {
    setBusy(id)
    setError('')
    try {
      await api.startRender(id)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy('')
    }
  }

  const remove = async (id: string) => {
    if (!window.confirm('删除这条成片记录？已生成的视频文件也会删除。')) return
    await api.deleteRender(id).catch(() => undefined)
    await load()
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>成片</h1>
          <p>所有项目的导出记录；草稿和失败的可以继续导出。</p>
        </div>
        <div className="row">
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">全部状态</option>
            <option value="draft">草稿</option>
            <option value="rendering">导出中</option>
            <option value="succeeded">已完成</option>
            <option value="failed">失败</option>
          </select>
          <button className="ghost" onClick={() => void load()}>刷新</button>
        </div>
      </div>

      {error && <div className="notice err">{error}</div>}

      <div className="list">
        {items.map((r) => {
          const running = ['queued', 'preparing', 'rendering'].includes(r.status)
          return (
            <div key={r.id} className="render-row">
              <div className="render-row-head">
                <span className={`badge ${r.status === 'failed' ? 'err' : r.status === 'succeeded' ? 'ok' : r.status === 'draft' ? '' : 'warn'}`}>
                  {STATUS_TEXT[r.status] || r.status}
                </span>
                <b>{r.project_name || r.project_id}</b>
                <span className="meta">{r.shot_ids.length} 镜 · {timeAgo(r.created_at)}</span>
                <div className="list-actions">
                  {r.status === 'succeeded' && r.output_url && (
                    <>
                      <a href={r.output_url} download={r.download_name}><button className="ghost tiny">下载</button></a>
                      <a href={r.output_url} target="_blank" rel="noreferrer"><button className="ghost tiny">预览</button></a>
                      <a href={`/api/renders/${r.id}/subtitles`}><button className="ghost tiny">字幕</button></a>
                    </>
                  )}
                  {(r.status === 'draft' || r.status === 'failed') && (
                    <button className="primary tiny" disabled={busy === r.id} onClick={() => void start(r.id)}>
                      {busy === r.id ? '启动中' : '继续导出'}
                    </button>
                  )}
                  <button className="ghost tiny" onClick={() => onOpenProject(r.project_id)}>去项目</button>
                  <button className="ghost tiny" onClick={() => void remove(r.id)}>删除</button>
                </div>
              </div>
              {running && (
                <>
                  <div className="bar"><i style={{ width: `${Math.round((r.progress || 0) * 100)}%` }} /></div>
                  <div className="meta">{r.message || '处理中'}</div>
                </>
              )}
              {r.status === 'failed' && r.error && <div className="err" style={{ marginTop: 6 }}>{r.error}</div>}
              {r.status === 'draft' && (
                <div className="meta">
                  草稿：{String((r.options as Record<string, unknown>)?.width || '')}×
                  {String((r.options as Record<string, unknown>)?.height || '')} · 点「继续导出」开始渲染
                </div>
              )}
            </div>
          )
        })}
        {!items.length && <div className="empty">还没有成片记录。去项目页导出一次，或先保存草稿。</div>}
      </div>
    </div>
  )
}
