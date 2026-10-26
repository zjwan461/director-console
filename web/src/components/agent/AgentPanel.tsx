import { useEffect, useMemo, useRef, useState } from 'react'
import { agentStream, api } from '../../api'
import type { AgentArtifact, AgentEvent, AgentMessage, AgentRun, AgentThread, Project } from '../../types'

interface Step {
  id: string
  node: string
  title: string
  status: string
  detail?: Record<string, unknown>
}

const ASPECTS = ['9:16', '16:9', '1:1', '4:3', '3:4', '21:9']

export default function AgentPanel({ projectId, onOpenProject }: {
  projectId: string
  onOpenProject: (projectId: string) => void
}) {
  const [projects, setProjects] = useState<Project[]>([])
  const [threads, setThreads] = useState<AgentThread[]>([])
  const [threadId, setThreadId] = useState('')
  const [messages, setMessages] = useState<AgentMessage[]>([])
  const [run, setRun] = useState<AgentRun | null>(null)
  const [steps, setSteps] = useState<Step[]>([])
  const [artifacts, setArtifacts] = useState<AgentArtifact[]>([])
  const [text, setText] = useState('')
  const [attachments, setAttachments] = useState<Array<{ id: string; url: string; name: string }>>([])
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement | null>(null)
  const [busy, setBusy] = useState(false)
  const [streamText, setStreamText] = useState('')
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [confirmDraft, setConfirmDraft] = useState<{ prompt: string; aspect: string } | null>(null)
  const streamStop = useRef<(() => void) | null>(null)
  const bottomRef = useRef<HTMLDivElement | null>(null)

  // 项目列表
  useEffect(() => {
    api.projects().then((res) => setProjects(res.items)).catch(() => undefined)
  }, [])

  const currentProject = useMemo(
    () => projects.find((p) => p.id === projectId) || null, [projects, projectId])

  // 切项目 → 拉会话（没有就建一个）
  useEffect(() => {
    if (!projectId) return
    let cancelled = false
    api.agentThreads(projectId).then(async (res) => {
      if (cancelled) return
      if (res.items.length) {
        setThreads(res.items)
        setThreadId((prev) => prev || res.items[0].id)
      } else {
        const thread = await api.agentCreateThread(projectId, '新对话')
        if (cancelled) return
        setThreads([thread])
        setThreadId(thread.id)
      }
    }).catch((err) => setError(String(err)))
    return () => { cancelled = true }
  }, [projectId])

  // 切会话 → 拉历史 + 活跃 run
  useEffect(() => {
    if (!threadId) return
    let cancelled = false
    setMessages([])
    setSteps([])
    setStreamText('')
    setArtifacts([])
    setRun(null)
    api.agentMessages(threadId).then((res) => {
      if (!cancelled) setMessages(res.items)
    }).catch(() => undefined)
    api.agentThread(threadId).then((res) => {
      if (cancelled) return
      setArtifacts(res.artifacts || [])
      const active = (res.runs || [])[0]
      if (active) setRun(active)
      if (active?.pending && Object.keys(active.pending).length) {
        const params = (active.pending.params || {}) as Record<string, unknown>
        setConfirmDraft({ prompt: String(params.prompt || ''), aspect: String(params.aspect || '9:16') })
      }
    }).catch(() => undefined)

    streamStop.current?.()
    streamStop.current = agentStream(threadId, handleEvent, (msg) => setError(msg))
    return () => { streamStop.current?.(); streamStop.current = null }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length, steps.length, run?.status])

  function handleEvent(raw: Record<string, unknown>) {
    const event = raw as unknown as AgentEvent
    if (event.t === 'step') {
      const step = event as unknown as Step & { detail?: Record<string, unknown> }
      setSteps((prev) => [...prev.filter((s) => s.id !== step.id), step])
    } else if (event.t === 'tool_call') {
      setSteps((prev) => [...prev, {
        id: String(event.id || Math.random()),
        node: String(event.name || 'tool'),
        title: String(event.name || '工具'),
        status: 'running',
        detail: (event.args || {}) as Record<string, unknown>,
      }])
    } else if (event.t === 'tool_result') {
      setSteps((prev) => prev.map((s) => (s.id === String(event.id)
        ? { ...s, status: event.ok ? 'done' : 'error', detail: event.data as Record<string, unknown> }
        : s)))
    } else if (event.t === 'need_confirm') {
      const params = (event.params || {}) as Record<string, unknown>
      // 这一轮已经停下来等确认，必须解除 busy，否则按钮是禁用的
      setBusy(false)
      setRun((prev) => prev ? { ...prev, status: 'waiting_confirm', pending: event as unknown as Record<string, unknown> } : prev)
      setConfirmDraft({ prompt: String(params.prompt || ''), aspect: String(params.aspect || '9:16') })
      api.agentThread(threadId).then((res) => setRun((res.runs || [])[0] || null)).catch(() => undefined)
    } else if (event.t === 'message_delta') {
      setStreamText((prev) => prev + String(event.text || ''))
    } else if (event.t === 'message') {
      setMessages((prev) => {
        if (prev.some((m) => m.id === event.message_id)) return prev
        return [...prev, {
          id: String(event.message_id || Math.random()),
          thread_id: threadId,
          role: (event.role as AgentMessage['role']) || 'assistant',
          content: String(event.content || ''),
          parts: (event.parts as AgentMessage['parts']) || [],
          seq: prev.length + 1,
          created_at: Date.now() / 1000,
        }]
      })
      setBusy(false)
      setStreamText('')
    } else if (event.t === 'artifact') {
      api.agentThread(threadId).then((res) => setArtifacts(res.artifacts || [])).catch(() => undefined)
      setArtifacts((prev) => [{
        id: String(event.artifact_id || Math.random()),
        kind: String(event.kind || 'image'),
        ref_id: String(event.ref_id || ''),
        url: String(event.url || ''),
        meta: { status: event.status },
        created_at: Date.now() / 1000,
      }, ...prev])
    } else if (event.t === 'run_end') {
      setBusy(false)
      setStreamText('')
      if (event.status === 'waiting_confirm') setBusy(false)
      setRun((prev) => prev ? { ...prev, status: (event.status as AgentRun['status']) || 'done' } : prev)
      // 用服务端记录覆盖本地乐观消息，避免重复
      api.agentMessages(threadId).then((res) => setMessages(res.items)).catch(() => undefined)
    }
  }

  async function send() {
    const value = text.trim()
    if ((!value && !attachments.length) || !threadId || busy) return
    setBusy(true)
    setError('')
    setText('')
    setSteps([])
    setStreamText('')
    try {
      const res = await api.agentSend(threadId, value, attachments.map((a) => a.id))
      setRun({ id: res.run_id, thread_id: threadId, status: 'running', node: '', pending: {}, error: '', steps: 0, started_at: Date.now() / 1000 })
      setMessages((prev) => [...prev, {
        id: `local_${Date.now()}`, thread_id: threadId, role: 'user', content: value,
        parts: attachments.map((a) => ({ type: 'image', url: a.url, asset_id: a.id, name: a.name })),
        seq: prev.length + 1, created_at: Date.now() / 1000,
      }])
      setAttachments([])
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setBusy(false)
    }
  }

  async function pickFiles(files: FileList | null) {
    if (!files?.length) return
    setUploading(true)
    try {
      const next: Array<{ id: string; url: string; name: string }> = []
      for (const file of Array.from(files).slice(0, 4)) {
        const asset = await api.upload(file, 'image')
        next.push({ id: asset.id, url: asset.url || `/media/files/${asset.path}`, name: asset.path.split('/').pop() || 'image' })
      }
      setAttachments((prev) => [...prev, ...next].slice(0, 4))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function decide(approved: boolean) {
    let target = run
    if (!target?.id) {
      try {
        const res = await api.agentThread(threadId)
        target = (res.runs || [])[0] || null
        if (target) setRun(target)
      } catch { /* 忽略 */ }
    }
    if (!target?.id) {
      setError('没有找到待确认的任务，可能已超时；重新发一次消息吧。')
      return
    }
    const params = approved && confirmDraft
      ? { ...(target.pending.params as Record<string, unknown> || {}), prompt: confirmDraft.prompt, aspect: confirmDraft.aspect }
      : undefined
    setBusy(true)
    try {
      await api.agentConfirm(target.id, approved, params)
      setConfirmDraft(null)
      setSteps([])
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function newThread() {
    if (!projectId) return
    const thread = await api.agentCreateThread(projectId, '新对话')
    setThreads((prev) => [thread, ...prev])
    setThreadId(thread.id)
  }

  if (!projectId) {
    return (
      <div className="agent-empty">
        <h2>导演助手</h2>
        <p>先选一个项目：助手的工作范围是项目，出图结果会落在项目里。</p>
        <select value="" onChange={(e) => onOpenProject(e.target.value)}>
          <option value="">选择项目…</option>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </div>
    )
  }

  const pending = (run?.status === 'waiting_confirm' ? run.pending : null) as
    { summary?: string; params?: Record<string, unknown> } | null

  return (
    <div className="agent-page">
      <div className="agent-main">
        <header className="agent-head">
          <div>
            <h1>导演助手</h1>
            <p className="meta">{currentProject?.name || projectId} · 用聊天出图</p>
          </div>
          <div className="agent-head-actions">
            <select value={threadId} onChange={(e) => setThreadId(e.target.value)}>
              {threads.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
            </select>
            <button className="ghost" onClick={() => void newThread()}>新对话</button>
          </div>
        </header>

        <div className="agent-feed">
          {messages.length === 0 && !steps.length && (
            <div className="agent-hint">
              <span className="agent-hint-title">说句话就能出图</span>
              <ul>
                {[
                  '画一只黑猫蹲在雪地里，竖屏，电影感',
                  '素材库里有哪些猫的图？',
                  '你能帮我做什么？',
                ].map((sample) => (
                  <li key={sample} onClick={() => setText(sample)}>{sample}</li>
                ))}
              </ul>
            </div>
          )}

          {messages.map((msg) => (
            <div key={msg.id} className={`agent-msg ${msg.role}`}>
              <div className="agent-bubble">{msg.content}</div>
              {msg.parts.map((part, index) => {
                if (part.type === 'assets') {
                  const items = (part.items || []) as Array<Record<string, unknown>>
                  return (
                    <div className="agent-assets" key={index}>
                      {items.map((item) => (
                        <figure key={String(item.id)}>
                          {String(item.kind) === 'image'
                            ? <img src={String(item.url)} alt="" loading="lazy" />
                            : <div className="agent-asset-icon">{String(item.kind)}</div>}
                          <figcaption>{String(item.path || '').split('/').pop()}</figcaption>
                        </figure>
                      ))}
                    </div>
                  )
                }
                if (part.type === 'image' || part.type === 'video') {
                  const url = String(part.url || '')
                  const isVideo = part.type === 'video'
                  return (
                    <div className="agent-artifact" key={index}>
                      {url
                        ? (isVideo
                          ? <video src={url} controls playsInline className="agent-artifact-video" />
                          : <img src={url} alt="" />)
                        : <div className="agent-artifact-empty">{isVideo ? '视频生成中…' : '生成中…'}</div>}
                      {url && <a href={url} download><button className="ghost tiny">下载</button></a>}
                    </div>
                  )
                }
                return null
              })}
            </div>
          ))}

          {streamText && (
            <div className="agent-msg assistant">
              <div className="agent-bubble">
                {streamText}
                <span className="agent-caret" />
              </div>
            </div>
          )}

          {steps.length > 0 && (
            <div className="agent-trace">
              {steps.map((step) => (
                <div key={step.id} className={`agent-step ${step.status}`}>
                  <button className="agent-step-head" onClick={() => setExpanded((prev) => ({ ...prev, [step.id]: !prev[step.id] }))}>
                    <span className="caret">{expanded[step.id] ? '▾' : '▸'}</span>
                    <span className="title">{step.title}</span>
                    <span className="status">{step.status === 'running' ? '进行中' : step.status === 'error' ? '失败' : '完成'}</span>
                  </button>
                  {expanded[step.id] && step.detail && (
                    <pre className="agent-step-detail">{JSON.stringify(step.detail, null, 2)}</pre>
                  )}
                </div>
              ))}
            </div>
          )}

          {pending && confirmDraft && (
            <div className="agent-confirm">
              <div className="agent-confirm-head">
                <b>{String(pending.summary || '确认执行')}</b>
                <span className="meta">确认后才会提交</span>
              </div>
              <label className="field">
                <span>画面描述</span>
                <textarea rows={3} value={confirmDraft.prompt}
                          onChange={(e) => setConfirmDraft({ ...confirmDraft, prompt: e.target.value })} />
              </label>
              <div className="row" style={{ gap: 8 }}>
                <label className="inline-field">
                  <span>画幅</span>
                  <select value={confirmDraft.aspect}
                          onChange={(e) => setConfirmDraft({ ...confirmDraft, aspect: e.target.value })}>
                    {ASPECTS.map((a) => <option key={a} value={a}>{a}</option>)}
                  </select>
                </label>
                {typeof pending.params?.width === 'number' && (
                  <span className="meta">{String(pending.params.width)} × {String(pending.params.height)}</span>
                )}
                {typeof pending.params?.duration === 'number' && (
                  <span className="meta">{String(pending.params.duration)} 秒</span>
                )}
              </div>
              <div className="agent-confirm-actions">
                <button className="primary" disabled={busy} onClick={() => void decide(true)}>执行</button>
                <button className="ghost" disabled={busy} onClick={() => void decide(false)}>取消</button>
              </div>
            </div>
          )}

          {busy && !pending && <div className="agent-typing">思考中…</div>}
          {error && <div className="notice err">{error}</div>}
          <div ref={bottomRef} />
        </div>

        <div className="agent-composer">
          <div className="agent-composer-box">
            {attachments.length > 0 && (
              <div className="agent-attach-row">
                {attachments.map((item) => (
                  <div className="agent-attach" key={item.id}>
                    <img src={item.url} alt={item.name} />
                    <button title="移除" onClick={() => setAttachments((prev) => prev.filter((x) => x.id !== item.id))}>×</button>
                  </div>
                ))}
              </div>
            )}
            <textarea
              rows={2}
              value={text}
              placeholder="说点什么，例如：画一只黑猫蹲在雪地里，竖屏"
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send() }
              }}
            />
            <div className="agent-composer-foot">
              <div className="agent-composer-tools">
                <button className="ghost tiny" disabled={uploading} onClick={() => fileRef.current?.click()}>
                  {uploading ? '上传中…' : '＋ 图片'}
                </button>
                <input ref={fileRef} type="file" accept="image/*" multiple hidden
                       onChange={(e) => void pickFiles(e.target.files)} />
                <span className="agent-composer-hint">Enter 发送 · Shift + Enter 换行</span>
              </div>
              <button className="primary" disabled={busy || (!text.trim() && !attachments.length)} onClick={() => void send()}>发送</button>
            </div>
          </div>
        </div>
      </div>

      <aside className="agent-canvas">
        <div className="agent-canvas-head">
          <h2>画布</h2>
          <span>{artifacts.length ? `${artifacts.length} 个产物` : '实时进度'}</span>
        </div>
        <div className="agent-run-card">
          <span className="meta">当前任务</span>
          <b>{run ? statusLabel(run.status) : '空闲'}</b>
          {run?.status === 'running' && <div className="agent-progress" />}
          {run?.error && <div className="notice err">{run.error.slice(0, 120)}</div>}
        </div>
        <div className="agent-artifacts">
          {artifacts.length === 0 && <div className="agent-empty-mini">出图后会出现在这里</div>}
          {artifacts.map((item) => {
            const label = item.kind === 'shot' ? '已存为镜头'
              : item.kind === 'render' ? '成片'
                : item.kind === 'video' ? '视频' : '图片'
            const status = item.url ? '' : String(item.meta?.status || '排队中')
            return (
              <a key={item.id} className="agent-artifact-card" href={item.url || '#'} target="_blank" rel="noreferrer">
                {item.kind === 'shot'
                  ? <div className="agent-shot-card">{String(item.meta?.title || '镜头')}</div>
                  : item.url
                    ? (item.kind === 'video' || item.kind === 'render'
                      ? <video src={item.url} muted playsInline preload="metadata" />
                      : <img src={item.url} alt="" loading="lazy" />)
                    : <div className="agent-artifact-empty">排队中</div>}
                <span>{label}{status ? ` · ${status}` : ''}</span>
              </a>
            )
          })}
        </div>
      </aside>
    </div>
  )
}

function statusLabel(status: string): string {
  if (status === 'waiting_confirm') return '等你确认'
  if (status === 'running') return '生成中'
  if (status === 'failed') return '失败'
  if (status === 'done') return '完成'
  if (status === 'canceled') return '已取消'
  return status
}
