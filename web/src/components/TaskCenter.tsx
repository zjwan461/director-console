import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'

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
  cancelable: boolean
}

const KIND_LABEL: Record<string, string> = {
  job: '生成',
  render: '成片',
  agent: '助手',
  ai_edit: 'AI 剪辑',
}

const STATUS_LABEL: Record<string, string> = {
  queued: '排队',
  preparing: '准备',
  uploading: '上传',
  running: '进行中',
  rendering: '渲染中',
  waiting_confirm: '待确认',
  succeeded: '完成',
  failed: '失败',
  canceled: '已取消',
  done: '完成',
  interrupted: '中断',
  draft: '草稿',
}

export default function TaskCenter() {
  const [items, setItems] = useState<TaskItem[]>([])
  const [active, setActive] = useState(0)
  const [error, setError] = useState('')
  const [onlyActive, setOnlyActive] = useState(false)
  const [busy, setBusy] = useState('')

  const load = useCallback(async () => {
    try {
      const res = await api.tasks(40, onlyActive)
      setItems(res.items)
      setActive(res.active)
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [onlyActive])

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => { void load() }, 4000)
    return () => window.clearInterval(timer)
  }, [load])

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

  return (
    <section className="panel task-center">
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ margin: 0 }}>任务中心 <span className="meta">进行中 {active}</span></h2>
        <div className="row" style={{ gap: 8 }}>
          <label className="check" style={{ margin: 0 }}>
            <input type="checkbox" checked={onlyActive} onChange={(e) => setOnlyActive(e.target.checked)} />
            只看进行中
          </label>
          <button className="ghost" onClick={() => void load()}>刷新</button>
        </div>
      </div>

      {error && <div className="notice err">{error}</div>}

      <div className="task-list">
        {items.length === 0 && <p className="meta">暂无任务</p>}
        {items.map((item) => (
          <div className={`task-row ${item.status}`} key={`${item.kind}:${item.id}`}>
            <span className={`task-kind ${item.kind}`}>{KIND_LABEL[item.kind] || item.kind}</span>
            <b className="task-title">{item.title}</b>
            <span className="task-status">{STATUS_LABEL[item.status] || item.status}</span>
            <span className="task-msg">
              {item.error ? item.error.slice(0, 60) : item.message.slice(0, 60)}
            </span>
            <span className="task-id">{item.id.slice(-6)}</span>
            {item.cancelable && (
              <button className="ghost tiny" disabled={busy === item.id} onClick={() => void cancel(item)}>
                取消
              </button>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
