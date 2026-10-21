import { useEffect, useMemo, useRef, useState } from 'react'
import { api, timeAgo } from '../api'
import type { Asset, Job, Preset, Project, Shot } from '../types'
import PresetFields, { makeDefaults } from './PresetForm'
import { OutputGrid, statusText } from './StudioPanel'

const MEDIA_TYPES = new Set(['image', 'video', 'audio'])

export default function ProjectsPanel({ onEdit }: { onEdit?: (projectId: string) => void }) {
  const [projects, setProjects] = useState<Project[]>([])
  const [projectId, setProjectId] = useState('')
  const [shots, setShots] = useState<Shot[]>([])
  const [shotId, setShotId] = useState('')
  const [cards, setCards] = useState<Preset[]>([])
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [assets, setAssetsState] = useState<Record<string, Asset>>({})
  const [takes, setTakes] = useState<Job[]>([])
  const [showAllTakes, setShowAllTakes] = useState(false)
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState('')
  const [newProject, setNewProject] = useState('')
  const [newTitle, setNewTitle] = useState('')
  const [busy, setBusy] = useState('')

  const setAssets = (updater: (prev: Record<string, Asset>) => Record<string, Asset>) =>
    setAssetsState((prev) => updater(prev))

  const initial = useMemo(() => {
    const params = new URLSearchParams(window.location.search)
    return { project: params.get('project') || '', shot: params.get('shot') || '' }
  }, [])
  const bootShotRef = useRef(false)

  const shot = useMemo(() => shots.find((s) => s.id === shotId) || null, [shots, shotId])
  const card = useMemo(() => cards.find((c) => c.id === shot?.preset_id) || null, [cards, shot])
  const prevShot = useMemo(() => {
    if (!shot) return null
    const idx = shots.findIndex((s) => s.id === shot.id)
    return idx > 0 ? shots[idx - 1] : null
  }, [shots, shot])

  useEffect(() => {
    void loadProjects()
    api.presets().then((res) => setCards(res.items)).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!projectId) return
    void loadShots(projectId)
  }, [projectId])

  useEffect(() => {
    if (!job) return
    if (['succeeded', 'failed', 'canceled'].includes(job.status)) {
      if (job.status === 'succeeded') {
        void loadShots(projectId, shotId)
        void loadTakes(shotId)
      }
      return
    }
    const timer = setInterval(() => {
      api.job(job.id).then(setJob).catch(() => undefined)
    }, 1800)
    return () => clearInterval(timer)
  }, [job, projectId, shotId])

  async function loadProjects() {
    try {
      const res = await api.projects()
      setProjects(res.items)
      const wanted = initial.project && res.items.some((p) => p.id === initial.project)
        ? initial.project
        : ''
      if (!projectId && res.items.length) setProjectId(wanted || res.items[0].id)
    } catch (err) {
      setError(String(err))
    }
  }

  async function loadShots(pid: string, keepId = '') {
    try {
      const res = await api.shots(pid)
      setShots(res.items)
      let next = keepId && res.items.some((s) => s.id === keepId) ? keepId : res.items[0]?.id || ''
      if (!bootShotRef.current && initial.shot && pid === initial.project
          && res.items.some((s) => s.id === initial.shot)) {
        next = initial.shot
      }
      bootShotRef.current = true
      if (next !== shotId) selectShot(res.items.find((s) => s.id === next) || null)
    } catch (err) {
      setError(String(err))
    }
  }

  async function loadTakes(id: string) {
    if (!id) return
    try {
      const res = await api.takes(id)
      setTakes(res.items)
    } catch {
      setTakes([])
    }
  }

  // 深链进入或首次加载时，cards 可能比 shot 晚到，selectShot 那一次拿不到字段定义，
  // 导致「素材」区域空白。这里在 card 就绪后把缺的素材预览补上。
  useEffect(() => {
    if (!shot || !card) return
    let cancelled = false
    void (async () => {
      for (const field of card.fields) {
        if (!MEDIA_TYPES.has(field.type)) continue
        const id = values[field.key]
        if (typeof id !== 'string' || !id || assets[field.key]) continue
        try {
          const asset = await api.asset(id)
          if (!cancelled) setAssetsState((prev) => ({ ...prev, [field.key]: asset }))
        } catch {
          // 素材可能已被清理，忽略
        }
      }
    })()
    return () => { cancelled = true }
  }, [shot?.id, card?.id, values])

  async function selectShot(next: Shot | null) {
    setShotId(next?.id || '')
    setAssetsState({})
    setJob(null)
    setTakes([])
    setShowAllTakes(false)
    if (!next) {
      setValues({})
      return
    }
    const nextCard = cards.find((c) => c.id === next.preset_id)
    const merged = nextCard ? { ...makeDefaults(nextCard), ...(next.values || {}) } : { ...(next.values || {}) }
    setValues(merged)
    void loadTakes(next.id)
    if (nextCard) {
      // 回填已选素材的预览
      for (const field of nextCard.fields) {
        if (!MEDIA_TYPES.has(field.type)) continue
        const id = merged[field.key]
        if (typeof id === 'string' && id) {
          try {
            const asset = await api.asset(id)
            setAssetsState((prev) => ({ ...prev, [field.key]: asset }))
          } catch {
            // 素材可能已被清理，忽略
          }
        }
      }
    }
  }

  const addProject = async () => {
    if (!newProject.trim()) return
    setBusy('project')
    try {
      const project = await api.createProject(newProject.trim())
      setNewProject('')
      await loadProjects()
      setProjectId(project.id)
    } catch (err) {
      setError(String(err))
    } finally {
      setBusy('')
    }
  }

  const removeProject = async (id: string) => {
    if (!window.confirm('删除项目会同时删除它的所有镜头，确定？')) return
    try {
      await api.deleteProject(id)
      setProjectId('')
      setShots([])
      setShotId('')
      setValues({})
      await loadProjects()
    } catch (err) {
      setError(String(err))
    }
  }

  const addShot = async () => {
    if (!projectId) return
    setBusy('shot')
    try {
      const presetId = cards[0]?.id || ''
      const created = await api.createShot(projectId, newTitle.trim() || `镜头 ${shots.length + 1}`, presetId)
      setNewTitle('')
      await loadShots(projectId, created.id)
    } catch (err) {
      setError(String(err))
    } finally {
      setBusy('')
    }
  }

  const saveShot = async () => {
    if (!shot) return
    try {
      await api.patchShot(shot.id, { values, title: shot.title })
      await loadShots(projectId, shot.id)
    } catch (err) {
      setError(String(err))
    }
  }

  const changePreset = async (presetId: string) => {
    if (!shot) return
    const nextCard = cards.find((c) => c.id === presetId)
    const nextValues = nextCard ? makeDefaults(nextCard) : {}
    setValues(nextValues)
    setAssetsState({})
    try {
      await api.patchShot(shot.id, { preset_id: presetId, values: nextValues })
      await loadShots(projectId, shot.id)
    } catch (err) {
      setError(String(err))
    }
  }

  const runningTakes = takes.filter((j) => ['queued', 'running'].includes(j.status))

  const generate = async () => {
    if (!shot || !card) return
    if (runningTakes.length) {
      const ok = window.confirm(
        `这个镜头已有 ${runningTakes.length} 个任务正在生成（${runningTakes
          .map((j) => statusText(j.status))
          .join('、')}）。\n继续提交会再排一个任务，可能同时占用显卡。\n\n仍要提交吗？`,
      )
      if (!ok) return
    }
    setError('')
    setBusy('generate')
    try {
      await api.patchShot(shot.id, { values })
      const created = await api.generateShot(shot.id, values)
      setJob(created)
      void loadTakes(shot.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy('')
    }
  }

  const usePrevFrame = async () => {
    if (!prevShot?.last_frame) return
    setValues((prev) => ({ ...prev, first_frame: prevShot.last_frame }))
    try {
      const asset = await api.asset(prevShot.last_frame)
      setAssetsState((prev) => ({ ...prev, first_frame: asset }))
    } catch {
      // ignore
    }
  }

  const moveShot = async (id: string, dir: -1 | 1) => {
    const idx = shots.findIndex((s) => s.id === id)
    const next = idx + dir
    if (idx < 0 || next < 0 || next >= shots.length) return
    const ids = shots.map((s) => s.id)
    ;[ids[idx], ids[next]] = [ids[next], ids[idx]]
    setShots((prev) => {
      const copy = [...prev]
      ;[copy[idx], copy[next]] = [copy[next], copy[idx]]
      return copy.map((s, i) => ({ ...s, idx: i }))
    })
    try {
      const res = await api.reorderShots(projectId, ids)
      setShots(res.items)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      void loadShots(projectId, shot?.id || '')
    }
  }

  const deleteShot = async (id: string) => {
    if (!window.confirm('删除这个镜头？')) return
    try {
      await api.deleteShot(id)
      await loadShots(projectId)
    } catch (err) {
      setError(String(err))
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>项目</h1>
          <p>一部片子 = 一个项目；一镜 = 一条镜头。上一镜的末帧可以直接拿来当下一镜的首帧。</p>
        </div>
      </div>

      {error && <div className="notice err">{error}</div>}

      <div className="split">
        <aside className="panel side">
          <h2>项目</h2>
          <div className="row" style={{ marginBottom: 10 }}>
            <input
              className="grow"
              placeholder="新项目名，例如：雪夜短片"
              value={newProject}
              onChange={(e) => setNewProject(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && void addProject()}
            />
            <button className="primary" disabled={busy === 'project'} onClick={() => void addProject()}>新建</button>
          </div>
          <div className="list">
            {projects.map((p) => (
              <div
                key={p.id}
                className={`list-item ${p.id === projectId ? 'active' : ''}`}
                onClick={() => { setProjectId(p.id); setShotId('') }}
              >
                <div>
                  <b title={p.name}>{p.name}</b>
                  <div className="meta">{p.shots ?? 0} 个镜头 · {timeAgo(p.created_at)}</div>
                </div>
                <div className="list-actions">
                  <button
                    className="ghost tiny"
                    onClick={(e) => { e.stopPropagation(); void removeProject(p.id) }}
                  >删</button>
                </div>
              </div>
            ))}
            {!projects.length && <div className="empty">还没有项目，先新建一个。</div>}
          </div>
        </aside>

        <section className="panel side">
          <h2>镜头</h2>
          {projectId ? (
            <>
              <div className="row" style={{ marginBottom: 10 }}>
                <input
                  className="grow"
                  placeholder="镜头标题（可留空）"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && void addShot()}
                />
                <button disabled={busy === 'shot'} onClick={() => void addShot()}>加一镜</button>
              </div>
              <div className="list">
                {shots.map((s) => {
                  const c = cards.find((x) => x.id === s.preset_id)
                  return (
                    <div
                      key={s.id}
                      className={`list-item ${s.id === shotId ? 'active' : ''}`}
                      onClick={() => void selectShot(s)}
                    >
                      {s.last_frame_url
                        ? <img className="mini" src={s.last_frame_url} alt="末帧" />
                        : <div className="mini placeholder">无</div>}
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <b title={s.title || `镜头 ${s.idx + 1}`}>{s.title || `镜头 ${s.idx + 1}`}</b>
                        <div className="meta">{c?.name || s.preset_id || '未选能力'}</div>
                      </div>
                      <div className="list-actions">
                        <button className="ghost tiny" onClick={(e) => { e.stopPropagation(); void moveShot(s.id, -1) }}>↑</button>
                        <button className="ghost tiny" onClick={(e) => { e.stopPropagation(); void moveShot(s.id, 1) }}>↓</button>
                      </div>
                    </div>
                  )
                })}
                {!shots.length && <div className="empty">还没有镜头，点「加一镜」。</div>}
              </div>
            </>
          ) : <div className="empty">先选择一个项目。</div>}
        </section>

        <section className="panel grow">
          {shot && card ? (
            <>
              <h2>
                <input
                  style={{ fontSize: 14, fontWeight: 600 }}
                  value={shot.title}
                  onChange={(e) => {
                    const title = e.target.value
                    setShots((prev) => prev.map((s) => (s.id === shot.id ? { ...s, title } : s)))
                  }}
                  onBlur={() => void saveShot()}
                />
                <button className="ghost tiny" onClick={() => void deleteShot(shot.id)}>删除镜头</button>
              </h2>

              <div className="row" style={{ marginBottom: 12 }}>
                <select value={shot.preset_id} onChange={(e) => void changePreset(e.target.value)}>
                  {cards.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
                {prevShot?.last_frame && card.fields.some((f) => f.key === 'first_frame') && (
                  <button className="ghost" onClick={() => void usePrevFrame()}>
                    用上一镜末帧 {prevShot.last_frame_ambiguous ? '（占位）' : ''}
                  </button>
                )}
                <button
                  className="ghost"
                  onClick={() => {
                    void saveShot().then(() => {
                      window.location.href = `/?tab=studio&fromShot=${shot.id}`
                    })
                  }}
                >
                  在创作台打开
                </button>
              </div>

              <PresetFields
                card={card}
                values={values}
                onChange={(key, value) => setValues((prev) => ({ ...prev, [key]: value }))}
                assets={assets}
                setAssets={setAssets}
                onError={setError}
              />

              <div className="row-actions">
                <button className="primary" disabled={busy === 'generate'} onClick={() => void generate()}>
                  {busy === 'generate' ? <><span className="spin" /> 提交中</> : '生成本镜'}
                </button>
                <button className="ghost" onClick={() => void saveShot()}>保存参数</button>
                {runningTakes.length > 0 && (
                  <span className="badge warn">本镜生成中（{runningTakes.length}）</span>
                )}
                {job && !runningTakes.length && <span className="badge">{statusText(job.status)} · {job.message}</span>}
              </div>

              {job?.error && <div className="notice err" style={{ marginTop: 10 }}>{job.error}</div>}
              {job && <OutputGrid job={job} />}

              {takes.length > 0 && (
                <div style={{ marginTop: 18 }}>
                  <h2>
                    <span>本镜历史（{takes.length}）</span>
                    {takes.length > 3 && (
                      <button className="ghost tiny" onClick={() => setShowAllTakes((v) => !v)}>
                        {showAllTakes ? '收起' : `展开全部（${takes.length}）`}
                      </button>
                    )}
                  </h2>
                  <div className={`job-list takes-scroll ${showAllTakes ? 'expanded' : ''}`}>
                    {takes.slice(0, showAllTakes ? takes.length : 3).map((take) => (
                      <div className="job" key={take.id}>
                        <div className="body">
                          <div className="title">
                            <span className={`badge ${take.status === 'succeeded' ? 'ok' : take.status === 'failed' ? 'err' : ''}`}>
                              {statusText(take.status)}
                            </span>
                            <span className="msg">{timeAgo(take.created_at)}</span>
                          </div>
                          {take.error && <div className="err">{take.error}</div>}
                          <OutputGrid job={take} />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="empty">
              {shot ? '这个镜头还没有选择能力卡。' : '从左边选一个镜头开始编辑。'}
            </div>
          )}
        </section>
      </div>

      {projectId && (
        <div className="panel">
          <h2>成片</h2>
          <p className="hint">剪辑（裁剪 / 字幕 / BGM）已移到独立的「剪辑」页，改动会自动保存。</p>
          <div className="row-actions">
            <button className="primary" disabled={!projectId} onClick={() => projectId && onEdit?.(projectId)}>
              去剪辑
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
