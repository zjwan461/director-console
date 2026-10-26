import { useCallback, useEffect, useState } from 'react'
import { api, timeAgo } from '../api'
import type { Job } from '../types'
import { OutputGrid } from './StudioPanel'

type Tab = 'agent' | 'studio' | 'projects' | 'edit' | 'assets' | 'renders' | 'jobs' | 'service'

interface TaskItem {
  id: string
  kind: string
  title: string
  status: string
  progress: number
  message: string
  error: string
  created_at: number
  project_id: string
  shot_id: string
  thread_id?: string
  outputs: Array<{ kind: string; url: string }>
  cancelable: boolean
  retryable: boolean
}

const PAGE = 20

const KIND_LABEL: Record<string, string> = {
  job: '生成', render: '成片', agent: '助手', ai_edit: '剪辑',
}

const STATUS_LABEL: Record<string, string> = {
  queued: '排队中', preparing: '准备中', uploading: '上传素材', running: '生成中',
  rendering: '渲染中', waiting_confirm: '待确认', succeeded: '已完成', failed: '失败',
  canceled: '已取消', done: '已完成', interrupted: '已中断', draft: '草稿',
}

const FILTERS: Array<[string, string]> = [
  ['', '全部'], ['job', '生成'], ['render', '成片'], ['agent', '助手'], ['ai_edit', '剪辑'],
]

const STATUS_FILTERS: Array<[string, string]> = [
  ['', '全部状态'], ['active', '进行中'], ['done', '已完成'], ['failed', '失败'],
]

export default function TaskCenter({ onNavigate }: {
  onNavigate?: (tab: Tab, params?: Record<string, string>) => void
}) {
  const [items, setItems] = useState<TaskItem[]>([])
  const [total, setTotal] = useState(0)
  const [active, setActive] = useState(0)
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [page, setPage] = useState(0)
  const [kind, setKind] = useState('')
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState('')
  const [busy, setBusy] = useState('')

  const load = useCallback(async () => {
    try {
      const res = await api.tasks({
        kind: kind || undefined,
        status: status || undefined,
        limit: PAGE,
        offset: page * PAGE,
      })
      // 页码越界（任务被删/筛选变化）时回退一页
      if (res.items.length === 0 && page > 0) {
        setPage((p) => Math.max(0, p - 1))
        return
      }
      setItems(res.items as unknown as TaskItem[])
      setTotal(res.total)
      setActive(res.active)
      setCounts(res.counts || {})
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [kind, status, page])

  useEffect(() => { void load() }, [load])

  useEffect(() => {
    const timer = window.setInterval(() => { void load() }, 4000)
    return () => window.clearInterval(timer)
  }, [load])

  useEffect(() => { setPage(0) }, [kind, status])

  const cancel = async (item: TaskItem) => {
    setBusy(item.id)
    try {
      if (item.kind === 'job') await api.cancelJob(item.id)
      else if (item.kind === 'render') await api.cancelRender(item.id)
      else if (item.kind === 'ai_edit') await api.aiEditCancel(item.id)
      else if (item.kind === 'agent') await api.agentCancel(item.id)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy('')
    }
  }

  const retry = async (item: TaskItem) => {
    setBusy(item.id)
    try {
      if (item.kind === 'job') await api.retryJob(item.id)
      else if (item.kind === 'render') await api.startRender(item.id)
      else if (item.kind === 'ai_edit') await api.aiEditRetry(item.id)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy('')
    }
  }

  const open = (item: TaskItem) => {
    if (!onNavigate) return
    if (item.kind === 'render') onNavigate('renders')
    else if (item.kind === 'agent') onNavigate('agent', item.project_id ? { project: item.project_id } : undefined)
    else if (item.kind === 'ai_edit') onNavigate('edit', item.project_id ? { project: item.project_id } : undefined)
    else if (item.kind === 'job' && item.project_id) onNavigate('projects', { project: item.project_id })
  }

  const pages = Math.max(1, Math.ceil(total / PAGE))

  return (
    <section className="panel task-center">
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'flex-end' }}>
        <div>
          <h2 style={{ margin: 0 }}>任务</h2>
          <p className="meta" style={{ margin: '4px 0 0' }}>
            生成 / 成片 / 助手 / AI 剪辑 · 共 {total} 条 · 进行中 {active}
          </p>
        </div>
        <button className="ghost" onClick={() => void load()}>刷新</button>
      </div>

      <div className="row task-filters">
        {FILTERS.map(([value, label]) => (
          <button key={value || 'all'}
                  className={`chip ${kind === value ? 'active' : ''}`}
                  onClick={() => setKind(value)}>
            {label}
            {value && counts[value] ? <span className="chip-count">{counts[value]}</span> : null}
          </button>
        ))}
        <span style={{ flex: 1 }} />
        {STATUS_FILTERS.map(([value, label]) => (
          <button key={value || 'all-status'}
                  className={`chip ${status === value ? 'active' : ''}`}
                  onClick={() => setStatus(value)}>
            {label}
          </button>
        ))}
      </div>

      {error && <div className="notice err">{error}</div>}

      <div className="task-table">
        {items.length === 0 && <p className="meta">没有符合条件的任务</p>}
        {items.map((item) => {
          const key = `${item.kind}:${item.id}`
          const openable = item.kind === 'render' || item.kind === 'agent' || item.kind === 'ai_edit'
          return (
            <div className={`task-item ${item.status}`} key={key}>
              <div className="task-row">
                <span className={`task-kind ${item.kind}`}>{KIND_LABEL[item.kind] || item.kind}</span>
                <b className="task-title" title={item.title}>{item.title}</b>
                <span className="task-status">{STATUS_LABEL[item.status] || item.status}</span>
                <span className="task-msg">
                  {item.error ? item.error.slice(0, 60) : item.message.slice(0, 60)}
                </span>
                <span className="task-time">{timeAgo(item.created_at)}</span>
                <div className="task-actions">
                  {item.cancelable && (
                    <button className="ghost tiny" disabled={busy === item.id}
                            onClick={() => void cancel(item)}>取消</button>
                  )}
                  {item.retryable && (
                    <button className="ghost tiny" disabled={busy === item.id}
                            onClick={() => void retry(item)}>重试</button>
                  )}
                  {item.outputs.length > 0 && (
                    <button className="ghost tiny"
                            onClick={() => setExpanded(expanded === key ? '' : key)}>
                      {expanded === key ? '收起' : `产物 ${item.outputs.length}`}
                    </button>
                  )}
                  {openable && (
                    <button className="ghost tiny" onClick={() => open(item)}>打开</button>
                  )}
                </div>
              </div>

              {item.cancelable && item.status !== 'waiting_confirm' && (
                <div className="bar"><i style={{ width: `${Math.round((item.progress || 0) * 100)}%` }} /></div>
              )}

              {expanded === key && item.outputs.length > 0 && (
                <div className="task-outputs">
                  <OutputGrid job={{
                    id: item.id,
                    status: item.status,
                    outputs: item.outputs,
                  } as unknown as Job} />
                </div>
              )}
            </div>
          )
        })}
      </div>

      <div className="task-pager">
        <button className="ghost" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>
          上一页
        </button>
        <span className="meta">第 {page + 1} / {pages} 页</span>
        <button className="ghost" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>
          下一页
        </button>
      </div>
    </section>
  )
}
