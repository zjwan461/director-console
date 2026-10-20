import { useCallback, useEffect, useState } from 'react'
import { api, formatBytes, timeAgo } from '../api'
import type { Asset, AssetUsage } from '../types'

const KIND_LABEL: Record<string, string> = { image: '图片', video: '视频', audio: '音频' }

export default function AssetsPanel({ onOpenProject }: { onOpenProject: (projectId: string, shotId?: string) => void }) {
  const [kind, setKind] = useState('')
  const [q, setQ] = useState('')
  const [items, setItems] = useState<Asset[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<Asset | null>(null)
  const [usage, setUsage] = useState<AssetUsage | null>(null)

  const PAGE = 60

  const load = useCallback(async (nextOffset = 0, append = false) => {
    setLoading(true)
    setError('')
    try {
      const res = await api.assets({ kind: kind || undefined, q: q || undefined, limit: PAGE, offset: nextOffset })
      setItems((prev) => (append ? [...prev, ...res.items] : res.items))
      setTotal(res.total)
      setOffset(nextOffset)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [kind, q])

  useEffect(() => { void load(0, false) }, [load])

  const open = async (asset: Asset) => {
    setSelected(asset)
    setUsage(null)
    try {
      setUsage(await api.assetUsage(asset.id))
    } catch {
      setUsage({ asset, shots: [], jobs: [] })
    }
  }

  const remove = async (asset: Asset) => {
    if (!window.confirm(`删除 ${asset.path.split('/').pop()}？文件也会删除，且无法恢复。`)) return
    try {
      await api.deleteAsset(asset.id)
      if (selected?.id === asset.id) {
        setSelected(null)
        setUsage(null)
      }
      await load(0, false)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>资产</h1>
          <p>所有生成结果与上传素材都在这里；点开可以看它被哪些镜头用过。</p>
        </div>
        <button className="ghost" onClick={() => void load(0, false)}>刷新</button>
      </div>

      <div className="row" style={{ marginBottom: 12 }}>
        {[['', '全部'], ['image', '图片'], ['video', '视频'], ['audio', '音频']].map(([value, label]) => (
          <button
            key={value}
            className={`chip ${kind === value ? 'active' : ''}`}
            onClick={() => setKind(value)}
          >
            {label}
          </button>
        ))}
        <input
          className="grow"
          style={{ maxWidth: 260 }}
          placeholder="按文件名搜索…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') void load(0, false) }}
        />
        <span style={{ fontSize: 12, color: 'var(--muted)' }}>共 {total} 个</span>
      </div>

      {error && <div className="notice err">{error}</div>}

      <div className={`assets-split ${selected ? 'with-detail' : ''}`}>
        <div className="asset-grid">
          {items.map((asset) => (
            <div
              key={asset.id}
              className={`asset-card ${selected?.id === asset.id ? 'active' : ''}`}
              onClick={() => void open(asset)}
            >
              <div className="asset-thumb">
                {asset.kind === 'image' && <img src={asset.url} alt={asset.path} loading="lazy" />}
                {asset.kind === 'video' && (
                  <>
                    <video src={asset.url} preload="none" muted />
                    <span className="asset-play">▶</span>
                  </>
                )}
                {asset.kind === 'audio' && <span className="asset-icon">音频</span>}
                <span className="asset-kind">{KIND_LABEL[asset.kind] || asset.kind}</span>
              </div>
              <div className="asset-meta">
                <b title={asset.path}>{asset.path.split('/').pop()}</b>
                <span>{formatBytes(asset.size)} · {timeAgo(asset.created_at || 0)}</span>
              </div>
            </div>
          ))}
          {!items.length && !loading && <div className="empty">还没有资产，去创作台生成一张图或一段视频。</div>}
        </div>

        {selected && (
          <aside className="panel asset-detail">
            <h2>
              <span>{KIND_LABEL[selected.kind] || selected.kind}</span>
              <button className="ghost tiny" onClick={() => { setSelected(null); setUsage(null) }}>关闭</button>
            </h2>

            <div className="asset-preview">
              {selected.kind === 'image' && <img src={selected.url} alt={selected.path} />}
              {selected.kind === 'video' && <video src={selected.url} controls />}
              {selected.kind === 'audio' && <audio src={selected.url} controls />}
            </div>

            <dl className="kv" style={{ marginTop: 10 }}>
              <dt>文件</dt><dd style={{ wordBreak: 'break-all' }}>{selected.path.split('/').pop()}</dd>
              <dt>大小</dt><dd>{formatBytes(selected.size)}</dd>
              {Number(selected.width) > 0 && (<><dt>尺寸</dt><dd>{selected.width} × {selected.height}</dd></>)}
              <dt>创建</dt><dd>{new Date((selected.created_at || 0) * 1000).toLocaleString()}</dd>
            </dl>

            <div className="row-actions">
              <a href={selected.url} download><button>下载</button></a>
              <button className="danger" onClick={() => void remove(selected)}>删除</button>
            </div>

            <h2 style={{ marginTop: 18 }}>被这些镜头使用（{usage?.shots.length ?? 0}）</h2>
            {!usage?.shots.length && <div className="msg" style={{ color: 'var(--muted)', fontSize: 12 }}>还没有镜头引用它。</div>}
            <div className="list">
              {usage?.shots.map((row) => (
                <div
                  key={row.shot_id + row.fields.join('')}
                  className="list-item"
                  onClick={() => onOpenProject(row.project_id, row.shot_id)}
                >
                  <div style={{ minWidth: 0 }}>
                    <b>{row.shot_title}</b>
                    <div className="meta">{row.project_name} · {row.fields.join(', ')}</div>
                  </div>
                </div>
              ))}
            </div>

            {usage && usage.jobs.length > 0 && (
              <>
                <h2 style={{ marginTop: 16 }}>来源任务（{usage.jobs.length}）</h2>
                <div className="list">
                  {usage.jobs.map((job) => (
                    <div key={job.id} className="list-item">
                      <div style={{ minWidth: 0 }}>
                        <b>{job.preset_id}</b>
                        <div className="meta">{job.status} · {timeAgo(job.created_at)}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </aside>
        )}
      </div>

      {items.length < total && (
        <div className="row-actions" style={{ marginTop: 12 }}>
          <button onClick={() => void load(offset + PAGE, true)} disabled={loading}>
            {loading ? '加载中…' : `加载更多（${total - items.length}）`}
          </button>
        </div>
      )}
    </div>
  )
}
