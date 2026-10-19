import { useEffect, useState } from 'react'
import { api, formatBytes } from '../api'
import type { Asset, Job, Preset } from '../types'
import PresetFields, { makeDefaults } from './PresetForm'

interface Props {
  onJobCreated: (job: Job) => void
  onGoJobs: () => void
  serviceReady: boolean
}

export default function StudioPanel({ onJobCreated, onGoJobs, serviceReady }: Props) {
  const [cards, setCards] = useState<Preset[]>([])
  const [selected, setSelected] = useState<Preset | null>(null)
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [assets, setAssetsState] = useState<Record<string, Asset>>({})
  const [activeJob, setActiveJob] = useState<Job | null>(null)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const setAssets = (updater: (prev: Record<string, Asset>) => Record<string, Asset>) =>
    setAssetsState((prev) => updater(prev))

  const selectCard = (card: Preset) => {
    setSelected(card)
    setValues(makeDefaults(card))
    setAssetsState({})
    setActiveJob(null)
    setError('')
  }

  useEffect(() => {
    api.presets().then((res) => {
      setCards(res.items)
      if (res.items.length) selectCard(res.items[0])
    }).catch((err) => setError(String(err)))
  }, [])

  useEffect(() => {
    if (!activeJob) return
    if (['succeeded', 'failed', 'canceled'].includes(activeJob.status)) return
    const timer = setInterval(() => {
      api.job(activeJob.id).then(setActiveJob).catch(() => undefined)
    }, 1800)
    return () => clearInterval(timer)
  }, [activeJob])

  const submit = async () => {
    if (!selected) return
    setError('')
    setSubmitting(true)
    try {
      const job = await api.createJob(selected.id, values)
      setActiveJob(job)
      onJobCreated(job)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>创作台</h1>
          <p>选一个能力，填画面描述、传参考素材，剩下的交给 ComfyUI。</p>
        </div>
        {!serviceReady && <span className="badge err">ComfyUI 未连接</span>}
      </div>

      <div className="card-grid">
        {cards.map((card) => (
          <div
            key={card.id}
            className={`card ${selected?.id === card.id ? 'active' : ''}`}
            onClick={() => selectCard(card)}
          >
            <h3>
              {card.name}
              {card.badge && <span className="badge">{card.badge}</span>}
              {card.error && <span className="badge err">不可用</span>}
            </h3>
            <p>{card.desc}</p>
            {card.hint && <div className="hint">{card.hint}</div>}
          </div>
        ))}
      </div>

      {selected && (
        <div className="panel" style={{ marginTop: 16 }}>
          <h2>
            <span>{selected.name}</span>
            <span style={{ color: 'var(--muted)', fontSize: 11 }}>{selected.id}</span>
          </h2>

          {selected.error && <div className="notice err">{selected.error}</div>}

          <PresetFields
            card={selected}
            values={values}
            onChange={(key, value) => setValues((prev) => ({ ...prev, [key]: value }))}
            assets={assets}
            setAssets={setAssets}
            onError={setError}
          />

          <div className="row-actions">
            <button className="primary" disabled={submitting || !!selected.error} onClick={() => void submit()}>
              {submitting ? <><span className="spin" /> 提交中</> : '开始生成'}
            </button>
            <button className="ghost" onClick={() => selectCard(selected)}>重置表单</button>
            <button className="ghost" onClick={onGoJobs}>查看全部任务</button>
            {error && <span style={{ color: 'var(--err)', fontSize: 12 }}>{error}</span>}
          </div>
        </div>
      )}

      {activeJob && (
        <div className="panel" style={{ marginTop: 16 }}>
          <h2>
            <span>当前任务</span>
            <span className={`badge ${activeJob.status === 'failed' ? 'err' : activeJob.status === 'succeeded' ? 'ok' : ''}`}>
              {statusText(activeJob.status)}
            </span>
          </h2>
          <div style={{ color: 'var(--muted)', fontSize: 12 }}>{activeJob.message || '—'}</div>
          <div className="bar"><i style={{ width: `${Math.round((activeJob.progress || 0) * 100)}%` }} /></div>
          {activeJob.error && <div className="notice err" style={{ marginTop: 10 }}>{activeJob.error}</div>}
          <OutputGrid job={activeJob} />
        </div>
      )}
    </div>
  )
}

export function OutputGrid({ job }: { job: Job }) {
  if (!job.outputs?.length) return null
  return (
    <div className="card-grid" style={{ marginTop: 12 }}>
      {job.outputs.map((out, idx) => (
        <div className="panel" key={`${out.url}-${idx}`} style={{ padding: 10 }}>
          {out.kind === 'video' && <video src={out.url} controls style={{ width: '100%', borderRadius: 8 }} />}
          {out.kind === 'image' && <img src={out.url} alt={out.name} style={{ width: '100%', borderRadius: 8 }} />}
          {out.kind === 'audio' && <audio src={out.url} controls style={{ width: '100%' }} />}
          {out.kind === 'file' && <a href={out.url} target="_blank" rel="noreferrer">{out.name}</a>}
          <div style={{ marginTop: 6, color: 'var(--muted)', fontSize: 12 }}>
            {out.name} {out.size ? `· ${formatBytes(out.size)}` : ''}{' '}
            <a href={out.url} download>下载</a>
          </div>
        </div>
      ))}
    </div>
  )
}

export function statusText(status: Job['status']): string {
  return {
    queued: '排队中',
    uploading: '上传素材',
    running: '生成中',
    succeeded: '已完成',
    failed: '失败',
    canceled: '已取消',
  }[status] || status
}
