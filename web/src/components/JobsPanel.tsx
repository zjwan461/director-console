import { useCallback, useEffect, useRef, useState } from 'react'
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

const PAGE_SIZE = 20

/** 把「首屏刷新」的新数据合并进已加载列表：更新已有项状态、头部插入新任务，保留已翻页的旧数据。 */
function mergeFresh(prev: Job[], fresh: Job[]): Job[] {
  const freshIds = new Set(fresh.map((job) => job.id))
  const cutoff = fresh.length ? fresh[fresh.length - 1].created_at : Number.NEGATIVE_INFINITY
  // 早于首屏末条的任务属于已翻页的历史数据，直接保留（不重复）。
  const tail = prev.filter((job) => job.created_at < cutoff && !freshIds.has(job.id))
  return [...fresh, ...tail]
}

export default function JobsPanel({ refreshKey }: Props) {
  const [jobs, setJobs] = useState<Job[]>([])
  const [filter, setFilter] = useState<'all' | Job['status']>('all')
  const [expanded, setExpanded] = useState<string>('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [hasMore, setHasMore] = useState(true)

  const cursorRef = useRef<string | null>(null)
  const loadingRef = useRef(false)
  const hasMoreRef = useRef(true)
  const sentinelRef = useRef<HTMLDivElement | null>(null)

  const statusParam = filter === 'all' ? undefined : filter

  const loadPage = useCallback(
    async (reset: boolean) => {
      if (loadingRef.current) return
      if (!reset && !hasMoreRef.current) return
      loadingRef.current = true
      setLoading(true)
      try {
        const cursor = reset ? null : cursorRef.current
        const res = await api.jobs(PAGE_SIZE, statusParam, cursor)
        setJobs((prev) => {
          if (reset) return res.items
          const seen = new Set(prev.map((job) => job.id))
          return [...prev, ...res.items.filter((job) => !seen.has(job.id))]
        })
        cursorRef.current = res.next_cursor
        hasMoreRef.current = res.has_more
        setHasMore(res.has_more)
        setError('')
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
      } finally {
        loadingRef.current = false
        setLoading(false)
      }
    },
    [statusParam],
  )

  // 切换分页/筛选时重置并加载首屏
  useEffect(() => {
    cursorRef.current = null
    hasMoreRef.current = true
    setHasMore(true)
    setJobs([])
    void loadPage(true)
  }, [refreshKey, filter, loadPage])

  // 首屏轮询：只刷新最新一页，合并更新状态 & 插入新任务（不影响已加载的历史与滚动位置）
  useEffect(() => {
    const timer = setInterval(() => {
      api
        .jobs(PAGE_SIZE, statusParam)
        .then((res) => setJobs((prev) => (prev.length ? mergeFresh(prev, res.items) : res.items)))
        .catch(() => undefined)
    }, 3000)
    return () => clearInterval(timer)
  }, [statusParam])

  // 滚动到底部自动加载下一页
  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) void loadPage(false)
      },
      { rootMargin: '200px' },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [loadPage, hasMore])

  const shown = filter === 'all' ? jobs : jobs.filter((job) => job.status === filter)

  const cancel = async (id: string) => {
    try {
      await api.cancelJob(id)
      void loadPage(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const retry = async (id: string) => {
    try {
      await api.retryJob(id)
      void loadPage(true)
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
      {!shown.length && !loading && <div className="empty">还没有任务。去创作台生成第一条吧。</div>}

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

      {/* 触底哨兵：进入视口即加载下一页 */}
      <div ref={sentinelRef} className="jobs-more">
        {loading ? '加载中…' : hasMore ? '下滑加载更多' : shown.length ? '没有更多了' : ''}
      </div>
    </div>
  )
}
