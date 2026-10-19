import { useEffect, useState } from 'react'
import { api, timeAgo } from '../api'
import type { Job } from '../types'
import { OutputGrid } from './StudioPanel'

interface Props {
  refreshKey: number
}

const STATUS_LABEL: Record<Job['status'], string> = {
  queued: '排队中',
  uploading: '上传素材',
  running: '生成中',
  succeeded: '已完成',
  failed: '失败',
  canceled: '已取消',
}

export default function JobsPanel({ refreshKey }: Props) {
  const [jobs, setJobs] = useState<Job[]>([])
  const [filter, setFilter] = useState<'all' | Job['status']>('all')
  const [expanded, setExpanded] = useState<string>('')
  const [error, setError] = useState('')

  const load = () => {
    api.jobs(60)
      .then((res) => setJobs(res.items))
      .catch((err) => setError(String(err)))
  }

  useEffect(() => {
    load()
    const timer = setInterval(load, 3000)
    return () => clearInterval(timer)
  }, [refreshKey])

  const shown = filter === 'all' ? jobs : jobs.filter((job) => job.status === filter)

  const cancel = async (id: string) => {
    try {
      await api.cancelJob(id)
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const retry = async (id: string) => {
    try {
      await api.retryJob(id)
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>任务</h1>
          <p>所有生成任务都在这里排队、执行、出片。</p>
        </div>
        <div className="tabs">
          {(['all', 'running', 'succeeded', 'failed'] as const).map((key) => (
            <button key={key} className={filter === key ? 'chip active' : 'chip'} onClick={() => setFilter(key)}>
              {key === 'all' ? '全部' : STATUS_LABEL[key as Job['status']]}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="notice err">{error}</div>}
      {!shown.length && <div className="empty">还没有任务。去创作台生成第一条吧。</div>}

      <div className="job-list">
        {shown.map((job) => (
          <div className="job" key={job.id}>
            <div className="body">
              <div className="title">
                <b>{job.preset_id}</b>
                <span className={`badge ${job.status === 'failed' ? 'err' : job.status === 'succeeded' ? 'ok' : job.status === 'canceled' ? 'warn' : ''}`}>
                  {STATUS_LABEL[job.status]}
                </span>
                <span className="msg">{timeAgo(job.created_at)}</span>
                <span className="msg">{job.id}</span>
              </div>
              <div className="msg">{job.message || '—'}</div>
              {job.status === 'running' && <div className="bar"><i style={{ width: `${Math.round(job.progress * 100)}%` }} /></div>}
              {job.error && <div className="err">{job.error}</div>}
              <div className="row" style={{ marginTop: 8 }}>
                {job.status === 'running' || job.status === 'queued' || job.status === 'uploading'
                  ? <button className="ghost" onClick={() => void cancel(job.id)}>取消</button>
                  : <button className="ghost" onClick={() => void retry(job.id)}>再来一次</button>}
                {job.outputs?.length > 0 && (
                  <button className="ghost" onClick={() => setExpanded(expanded === job.id ? '' : job.id)}>
                    {expanded === job.id ? '收起产物' : `查看产物（${job.outputs.length}）`}
                  </button>
                )}
              </div>
              {expanded === job.id && <OutputGrid job={job} />}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
