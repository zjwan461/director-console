import { useState } from 'react'
import { api } from '../api'
import type { ModelCheckResult } from '../types'

export default function ModelCheckPanel() {
  const [result, setResult] = useState<ModelCheckResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [onlyMissing, setOnlyMissing] = useState(true)
  const [open, setOpen] = useState('')
  const [copied, setCopied] = useState('')
  const [note, setNote] = useState('')
  const [syncing, setSyncing] = useState(false)

  const run = async () => {
    setLoading(true)
    setError('')
    setCopied('')
    try {
      const res = await api.modelsCheck()
      setResult(res)
      const first = res.cards.find((c) => c.missing_count > 0)
      setOpen(first ? first.id : '')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  const syncSources = async () => {
    setSyncing(true)
    setError('')
    try {
      const res = await api.syncModelSources()
      setNote(`已从 ComfyUI 工作流同步 ${res.updated} 条模型链接（共 ${res.after} 条）`)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSyncing(false)
    }
  }

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(text)
      setTimeout(() => setCopied(''), 1500)
    } catch {
      setError('复制失败，请手动选中命令复制')
    }
  }

  return (
    <div className="panel">
      <h2>
        <span>模型检查</span>
        {result && (
          <span className={`badge ${result.summary.missing ? 'err' : 'ok'}`}>
            {result.summary.missing ? `${result.summary.missing} 个缺失` : '全部齐全'}
          </span>
        )}
      </h2>

      <p style={{ color: 'var(--muted)', fontSize: 12, marginTop: 0 }}>
        对照当前连接的 ComfyUI 的模型清单，检查每张能力卡依赖的模型；缺失的会给出下载命令模板。
      </p>

      <div className="row" style={{ marginBottom: 10 }}>
        <span style={{ fontSize: 12, color: 'var(--muted)' }}>对比来源：当前连接的 ComfyUI</span>
        <button disabled={syncing} onClick={() => void syncSources()}>
          {syncing ? <><span className="spin" /> 同步中</> : '从 ComfyUI 同步模型链接'}
        </button>
      </div>

      {note && <div className="notice" style={{ marginBottom: 10 }}>{note}</div>}

      <div className="row-actions" style={{ marginBottom: 10 }}>
        <button className="primary" disabled={loading} onClick={() => void run()}>
          {loading ? <><span className="spin" /> 检查中</> : '一键检查全部能力卡'}
        </button>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--muted)' }}>
          <input type="checkbox" checked={onlyMissing} onChange={(e) => setOnlyMissing(e.target.checked)} />
          只看缺失
        </label>
        {result && (
          <span style={{ fontSize: 12, color: 'var(--muted)' }}>
            {result.summary.cards} 张卡 · {result.summary.models} 个模型引用 ·
            {' '}{result.summary.missing} 个缺失 · 来源 {result.comfy.base_url}
          </span>
        )}
      </div>

      {error && <div className="notice err">{error}</div>}

      {result && (
        <div className="job-list">
          {result.cards.map((card) => {
            const models = onlyMissing ? card.models.filter((m) => !m.exists) : card.models
            const expanded = open === card.id
            return (
              <div className="job" key={card.id}>
                <div className="body">
                  <div className="title">
                    <b>{card.name}</b>
                    <span className={`badge ${card.missing_count ? 'err' : 'ok'}`}>
                      {card.missing_count ? `${card.missing_count}/${card.total} 缺失` : '全部就绪'}
                    </span>
                    <button className="ghost tiny" onClick={() => setOpen(expanded ? '' : card.id)}>
                      {expanded ? '收起' : '查看'}
                    </button>
                  </div>

                  {expanded && (
                    models.length === 0 ? (
                      <div className="msg" style={{ marginTop: 6 }}>没有缺失模型。</div>
                    ) : (
                      models.map((m) => (
                        <div key={m.category + ':' + m.file} style={{ marginTop: 10 }}>
                          <div style={{ fontSize: 13 }}>
                            <span style={{ color: m.exists ? 'var(--ok)' : 'var(--err)' }}>{m.exists ? '✓' : '✗'} </span>
                            {m.file}
                            <span className="meta" style={{ marginLeft: 8, color: 'var(--muted)', fontSize: 11 }}>
                              {m.category} · {m.node}
                              {m.url ? ' · 链接来自工作流' : ''}
                            </span>
                          </div>
                          {!m.exists && (
                            <>
                              <pre className="logs" style={{ marginTop: 6 }}>{m.command}</pre>
                              <div className="row" style={{ marginTop: 4 }}>
                                <button className="ghost tiny" onClick={() => void copy(m.command)}>
                                  {copied === m.command ? '已复制' : '复制命令'}
                                </button>
                                <a href={m.search_url} target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>
                                  在 HuggingFace 搜索
                                </a>
                              </div>
                            </>
                          )}
                        </div>
                      ))
                    )
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
