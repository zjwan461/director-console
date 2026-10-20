import { useEffect, useState } from 'react'
import { api, formatBytes } from '../api'
import type { Asset, Job, Preset, Project, Shot } from '../types'
import PresetFields, { makeDefaults } from './PresetForm'

interface Props {
  onJobCreated: (job: Job) => void
  onGoJobs: () => void
  serviceReady: boolean
}

const MEDIA_TYPES = new Set(['image', 'video', 'audio'])

export default function StudioPanel({ onJobCreated, onGoJobs, serviceReady }: Props) {
  const [cards, setCards] = useState<Preset[]>([])
  const [selected, setSelected] = useState<Preset | null>(null)
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [assets, setAssetsState] = useState<Record<string, Asset>>({})
  const [activeJob, setActiveJob] = useState<Job | null>(null)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // 从项目镜头带参数进来
  const [fromShot, setFromShot] = useState<Shot | null>(null)
  // 保存为镜头
  const [saveOpen, setSaveOpen] = useState(false)
  const [projects, setProjects] = useState<Project[]>([])
  const [saveProjectId, setSaveProjectId] = useState('')
  const [saveTitle, setSaveTitle] = useState('')
  const [saveBusy, setSaveBusy] = useState(false)
  const [savedShot, setSavedShot] = useState<Shot | null>(null)
  const [notice, setNotice] = useState('')

  const setAssets = (updater: (prev: Record<string, Asset>) => Record<string, Asset>) =>
    setAssetsState((prev) => updater(prev))

  const loadAssets = async (card: Preset, merged: Record<string, unknown>) => {
    for (const field of card.fields) {
      if (!MEDIA_TYPES.has(field.type)) continue
      const id = merged[field.key]
      if (typeof id !== 'string' || !id) continue
      try {
        const asset = await api.asset(id)
        setAssetsState((prev) => ({ ...prev, [field.key]: asset }))
      } catch {
        // 素材可能已被清理
      }
    }
  }

  const selectCard = (card: Preset) => {
    setSelected(card)
    setValues(makeDefaults(card))
    setAssetsState({})
    setActiveJob(null)
    setError('')
    setFromShot(null)
    setSavedShot(null)
    setNotice('')
    setSaveOpen(false)
  }

  useEffect(() => {
    api.presets().then(async (res) => {
      setCards(res.items)
      const fromShotId = new URLSearchParams(window.location.search).get('fromShot')
      if (fromShotId) {
        try {
          const shot = await api.shot(fromShotId)
          const card = res.items.find((c) => c.id === shot.preset_id)
          if (card) {
            const merged = { ...makeDefaults(card), ...(shot.values || {}) }
            setSelected(card)
            setValues(merged)
            setFromShot(shot)
            await loadAssets(card, merged)
            return
          }
        } catch {
          // 镜头不存在就退回默认
        }
      }
      const cardId = new URLSearchParams(window.location.search).get('card')
      const wanted = cardId ? res.items.find((c) => c.id === cardId) : null
      if (wanted) selectCard(wanted)
      else if (res.items.length) selectCard(res.items[0])
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
      setSavedShot(null)
      setSaveOpen(false)
      onJobCreated(job)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  const openSave = async () => {
    setSaveOpen(true)
    setNotice('')
    try {
      const res = await api.projects()
      setProjects(res.items)
      if (!saveProjectId && res.items.length) setSaveProjectId(res.items[0].id)
    } catch (err) {
      setError(String(err))
    }
  }

  const saveAsShot = async () => {
    if (!activeJob || !saveProjectId) return
    setSaveBusy(true)
    setError('')
    try {
      const shot = await api.saveJobAsShot(activeJob.id, saveProjectId, saveTitle)
      setSavedShot(shot)
      setActiveJob({ ...activeJob, project_id: shot.project_id, shot_id: shot.id })
      setSaveOpen(false)
      setSaveTitle('')
      setNotice(`已保存为镜头「${shot.title}」，可以去项目页继续编辑或合成。`)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaveBusy(false)
    }
  }

  const saveBackToShot = async () => {
    if (!fromShot) return
    try {
      await api.patchShot(fromShot.id, { values })
      setNotice(`已把当前参数覆盖回镜头「${fromShot.title}」`)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
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

      {fromShot && (
        <div className="notice" style={{ marginBottom: 12, display: 'flex', gap: 12, alignItems: 'center' }}>
          <span style={{ flex: 1 }}>
            正在编辑项目镜头「{fromShot.title || '未命名'}」的参数；试完可以覆盖回该镜头。
          </span>
          <button className="ghost" onClick={() => void saveBackToShot()}>保存回该镜头</button>
          <a href="?tab=projects"><button className="ghost">返回项目</button></a>
        </div>
      )}
      {notice && <div className="notice" style={{ marginBottom: 12 }}>{notice}</div>}
      {savedShot && (
        <div className="notice" style={{ marginBottom: 12, display: 'flex', gap: 12, alignItems: 'center' }}>
          <span style={{ flex: 1 }}>这次结果已存为镜头「{savedShot.title}」。</span>
          <a href="?tab=projects"><button className="ghost">去项目页</button></a>
        </div>
      )}

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

      <div className="studio-split">
      {selected && (
        <div className="panel">
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
            <button className="ghost" onClick={() => selectCard(selected)}>重置表单</button>
            <button className="ghost" onClick={onGoJobs}>查看全部任务</button>
            {error && <span style={{ color: 'var(--err)', fontSize: 12 }}>{error}</span>}
          </div>

          <div className="sticky-bar">
            <span style={{ fontSize: 12, color: 'var(--muted)' }}>
              {selected.name} · {summaryText(selected, values)}
            </span>
            <button className="primary" disabled={submitting || !!selected.error} onClick={() => void submit()}>
              {submitting ? <><span className="spin" /> 提交中</> : '开始生成'}
            </button>
          </div>
        </div>
      )}

      {selected && !activeJob && (
        <div className="panel empty">生成后结果显示在这里</div>
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

          {activeJob.status === 'succeeded' && !activeJob.shot_id && !savedShot && (
            <div style={{ marginTop: 12 }}>
              {!saveOpen ? (
                <button onClick={() => void openSave()}>保存为镜头…</button>
              ) : (
                <div className="assist">
                  <b>保存为镜头</b>
                  <small>把这次的参数和产物挂到某个项目下，之后能在项目页继续改、接末帧、进成片。</small>
                  {!projects.length ? (
                    <div className="notice">还没有项目。先去「项目」页新建一个。</div>
                  ) : (
                    <>
                      <div className="row">
                        <select value={saveProjectId} onChange={(e) => setSaveProjectId(e.target.value)}>
                          {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                        </select>
                        <input
                          className="grow"
                          placeholder="镜头标题（可留空自动编号）"
                          value={saveTitle}
                          onChange={(e) => setSaveTitle(e.target.value)}
                        />
                      </div>
                      <div className="row">
                        <button className="primary" disabled={saveBusy || !saveProjectId} onClick={() => void saveAsShot()}>
                          {saveBusy ? <><span className="spin" /> 保存中</> : '保存'}
                        </button>
                        <button className="ghost" onClick={() => setSaveOpen(false)}>取消</button>
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          )}

          {activeJob.shot_id && !savedShot && (
            <div className="notice" style={{ marginTop: 10 }}>
              该任务已归属镜头 {activeJob.shot_id}。
            </div>
          )}
        </div>
      )}
      </div>
    </div>
  )
}

function summaryText(card: Preset, values: Record<string, unknown>): string {
  const parts: string[] = []
  const sizeField = card.fields.find((f) => f.type === 'size')
  if (sizeField) {
    const size = values[sizeField.key] as { aspect?: string; megapixels?: number } | undefined
    if (size) parts.push(`${size.aspect || ''} · ${size.megapixels ?? ''} MP`)
  }
  const durationField = card.fields.find((f) => f.type === 'duration')
  if (durationField) parts.push(`${values[durationField.key] ?? ''} 秒`)
  const seedField = card.fields.find((f) => f.type === 'seed')
  if (seedField) {
    const seed = Number(values[seedField.key] ?? -1)
    parts.push(seed < 0 ? '随机种子' : `种子 ${seed}`)
  }
  return parts.filter(Boolean).join(' · ')
}

export function OutputGrid({ job }: { job: Job }) {
  if (!job.outputs?.length) return null
  return (
    <div className="card-grid" style={{ marginTop: 12 }}>
      {job.outputs.map((out, idx) => (
        <div className="panel" key={`${out.url}-${out.name}-${idx}`} style={{ padding: 10 }}>
          {out.kind === 'video' && <video src={out.url} controls style={{ width: '100%', borderRadius: 8 }} />}
          {out.kind === 'image' && <img src={out.url} alt={out.name} style={{ width: '100%', borderRadius: 8 }} />}
          {out.kind === 'audio' && <audio src={out.url} controls style={{ width: '100%' }} />}
          {out.kind === 'text' && (
            <>
              <pre className="logs" style={{ maxHeight: 320, whiteSpace: 'pre-wrap' }}>{out.text}</pre>
              <button
                className="ghost"
                style={{ marginTop: 6 }}
                onClick={() => void navigator.clipboard.writeText(out.text || '')}
              >
                复制文本
              </button>
            </>
          )}
          {out.kind === 'file' && <a href={out.url} target="_blank" rel="noreferrer">{out.name}</a>}
          {out.kind !== 'text' && (
            <div style={{ marginTop: 6, color: 'var(--muted)', fontSize: 12 }}>
              {out.name} {out.size ? `· ${formatBytes(out.size)}` : ''}{' '}
              {out.url && <a href={out.url} download>下载</a>}
            </div>
          )}
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
