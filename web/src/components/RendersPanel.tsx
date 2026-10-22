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
  canceled: '已取消',
}

const TRANS_TEXT: Record<string, string> = {
  none: '',
  fade: '淡入淡出',
  dissolve: '交叉溶解',
}

function humanSize(bytes?: number) {
  if (!bytes) return ''
  const mb = bytes / 1024 / 1024
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`
}

export default function RendersPanel({ onOpenProject }: { onOpenProject: (projectId: string) => void }) {
  const [items, setItems] = useState<Render[]>([])
  const [filter, setFilter] = useState('')
  const [showPreview, setShowPreview] = useState(false)
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

  const cancel = async (id: string) => {
    try {
      await api.cancelRender(id)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const remove = async (id: string) => {
    if (!window.confirm('删除这条成片记录？已生成的视频文件也会删除。')) return
    await api.deleteRender(id).catch(() => undefined)
    await load()
  }

  const visible = showPreview ? items : items.filter((r) => !r.is_preview)
  const previewCount = items.filter((r) => r.is_preview).length

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>成片</h1>
          <p>正式导出记录。预览草稿默认折叠，勾选后可查看。</p>
        </div>
        <div className="row">
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">全部状态</option>
            <option value="draft">草稿</option>
            <option value="rendering">导出中</option>
            <option value="succeeded">已完成</option>
            <option value="failed">失败</option>
            <option value="canceled">已取消</option>
          </select>
          <label className="check" style={{ margin: 0 }}>
            <input type="checkbox" checked={showPreview} onChange={(e) => setShowPreview(e.target.checked)} />
            显示预览草稿{previewCount ? `（${previewCount}）` : ''}
          </label>
          <button className="ghost" onClick={() => void load()}>刷新</button>
        </div>
      </div>

      {error && <div className="notice err">{error}</div>}

      <div className="list">
        {visible.map((r) => {
          const running = ['queued', 'preparing', 'rendering'].includes(r.status)
          const s = r.summary
          const tags: string[] = []
          if (s?.width && s?.height) tags.push(`${s.height >= s.width ? '竖屏' : '横屏'} ${s.width}×${s.height}`)
          if (r.duration) tags.push(`${r.duration.toFixed(1)}s`)
          if (s?.subtitles) tags.push('字幕')
          if (s?.bgm) tags.push('BGM')
          if (s?.transition && TRANS_TEXT[s.transition]) tags.push(TRANS_TEXT[s.transition])
          if (s?.title) tags.push(`片头「${s.title}」`)
          if (s?.tail) tags.push(`片尾「${s.tail}」`)
          return (
            <div key={r.id} className={`render-card ${r.is_preview ? 'preview' : ''}`}>
              <div className="render-card-cover">
                {r.cover_url
                  ? <img src={r.cover_url} alt="封面" />
                  : <div className="cover-empty">无封面</div>}
              </div>
              <div className="render-card-body">
                <div className="render-card-title">
                  <span className={`badge ${r.status === 'failed' ? 'err' : r.status === 'succeeded' ? 'ok' : r.status === 'draft' ? '' : 'warn'}`}>
                    {STATUS_TEXT[r.status] || r.status}
                  </span>
                  {r.is_preview && <span className="badge">预览草稿</span>}
                  <b>{r.project_name || r.project_id}</b>
                  <span className="meta">{r.shot_ids.length} 镜 · {timeAgo(r.created_at)}</span>
                  {r.size_bytes ? <span className="meta">{humanSize(r.size_bytes)}</span> : null}
                </div>
                {tags.length > 0 && (
                  <div className="render-card-tags">
                    {tags.map((tag) => <span key={tag} className="tag">{tag}</span>)}
                  </div>
                )}
                {running && (
                  <>
                    <div className="bar"><i style={{ width: `${Math.round((r.progress || 0) * 100)}%` }} /></div>
                    <div className="meta">{r.message || '处理中'}</div>
                  </>
                )}
                {r.status === 'failed' && r.error && <div className="err" style={{ fontSize: 12 }}>{r.error}</div>}
              </div>
              <div className="render-card-actions">
                {r.status === 'succeeded' && r.output_url && (
                  <>
                    <a href={r.output_url} target="_blank" rel="noreferrer"><button className="ghost tiny">播放</button></a>
                    <a href={r.output_url} download={r.download_name}><button className="primary tiny">下载</button></a>
                    <a href={`/api/renders/${r.id}/subtitles`}><button className="ghost tiny">字幕</button></a>
                  </>
                )}
                {running && <button className="ghost tiny" onClick={() => void cancel(r.id)}>取消</button>}
                {(r.status === 'draft' || r.status === 'failed') && (
                  <button className="primary tiny" disabled={busy === r.id} onClick={() => void start(r.id)}>
                    {busy === r.id ? '启动中' : '继续导出'}
                  </button>
                )}
                <button className="ghost tiny" onClick={() => onOpenProject(r.project_id)}>去项目</button>
                <button className="ghost tiny" onClick={() => void remove(r.id)}>删除</button>
              </div>
            </div>
          )
        })}
        {!visible.length && (
          <div className="empty">
            {showPreview ? '还没有成片记录。' : '还没有正式导出的成片。去项目页导出一次，或勾选「显示预览草稿」。'}
          </div>
        )}
      </div>
    </div>
  )
}
