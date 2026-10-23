import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import type { Job, ServiceStatus } from './types'
import ServicePanel from './components/ServicePanel'
import StudioPanel from './components/StudioPanel'
import JobsPanel from './components/JobsPanel'
import ProjectsPanel from './components/ProjectsPanel'
import AssetsPanel from './components/AssetsPanel'
import RendersPanel from './components/RendersPanel'
import EditPanel from './components/EditPanel'
import AgentPanel from './components/agent/AgentPanel'

type Tab = 'agent' | 'studio' | 'projects' | 'edit' | 'assets' | 'renders' | 'jobs' | 'service'

const TAB_KEYS: Tab[] = ['agent', 'studio', 'projects', 'edit', 'assets', 'renders', 'jobs', 'service']

function initialTab(): Tab {
  const fromUrl = new URLSearchParams(window.location.search).get('tab')
  return (TAB_KEYS as string[]).includes(fromUrl || '') ? (fromUrl as Tab) : 'studio'
}

interface Toast {
  id: string
  kind: 'ok' | 'err'
  title: string
  text: string
  tab?: Tab
}

const TERMINAL = new Set(['succeeded', 'failed'])

// 侧边栏角标：记录每个 tab 上次“看过”的时间点
type BadgeKey = 'jobs' | 'renders'
const badgeSeenKey = (key: BadgeKey) => `dsh.seen.${key}`

function readSeen(key: BadgeKey): number {
  const raw = window.localStorage.getItem(badgeSeenKey(key))
  const value = Number(raw || 0)
  return Number.isFinite(value) ? value : 0
}

function writeSeen(key: BadgeKey, at: number) {
  window.localStorage.setItem(badgeSeenKey(key), String(at))
}



export default function App() {
  const [tab, setTabState] = useState<Tab>(initialTab)
  const [status, setStatus] = useState<ServiceStatus | null>(null)
  const [jobsRefresh, setJobsRefresh] = useState(0)
  const [toasts, setToasts] = useState<Toast[]>([])
  const known = useRef<Map<string, string> | null>(null)
  const [badges, setBadges] = useState<{ jobs: number; renders: number }>({ jobs: 0, renders: 0 })

  const setTab = (next: Tab) => {
    setTabState(next)
    const url = new URL(window.location.href)
    if (next === 'studio') url.searchParams.delete('tab')
    else url.searchParams.set('tab', next)
    window.history.replaceState({}, '', url)
  }

  // 角标：统计上次查看之后新完成的任务/成片
  useEffect(() => {
    // 第一次使用（没有记录）时把“已读时间”初始化到现在，避免历史记录全变成未读
    for (const key of ['jobs', 'renders'] as BadgeKey[]) {
      if (!window.localStorage.getItem(badgeSeenKey(key))) {
        writeSeen(key, Date.now() / 1000)
      }
    }
  }, [])

  useEffect(() => {
    let stopped = false
    const tick = async () => {
      try {
        const res = await api.newCounts(readSeen('jobs'), readSeen('renders'))
        if (!stopped) setBadges(res)
      } catch { /* 忽略网络抖动 */ }
    }
    void tick()
    const timer = window.setInterval(tick, 5000)
    return () => { stopped = true; window.clearInterval(timer) }
  }, [])

  // 进入任务/成片页即视为已读
  useEffect(() => {
    if (tab === 'jobs') {
      writeSeen('jobs', Date.now() / 1000 + 1)
      setBadges((prev) => ({ ...prev, jobs: 0 }))
    }
    if (tab === 'renders') {
      writeSeen('renders', Date.now() / 1000 + 1)
      setBadges((prev) => ({ ...prev, renders: 0 }))
    }
  }, [tab])

  const refreshStatus = useCallback(() => {
    api.serviceStatus().then(setStatus).catch(() => setStatus(null))
  }, [])

  useEffect(() => {
    refreshStatus()
    const timer = setInterval(refreshStatus, 5000)
    return () => clearInterval(timer)
  }, [refreshStatus])

  const pushToast = useCallback((toast: Omit<Toast, 'id'>) => {
    const id = Math.random().toString(36).slice(2)
    setToasts((prev) => [...prev.slice(-3), { ...toast, id }])
    window.setTimeout(() => setToasts((prev) => prev.filter((x) => x.id !== id)), 8000)
  }, [])

  // 全局轮询：任务 / 成片 从“进行中”变成“成功/失败”时右上角弹提示
  useEffect(() => {
    let stopped = false
    const tick = async () => {
      try {
        const [jobRes, renderRes] = await Promise.all([
          api.jobs(20).catch(() => ({ items: [] as Job[] })),
          api.allRenders(20).catch(() => ({ items: [] as never[] })),
        ])
        const current = new Map<string, string>()
        for (const job of jobRes.items) current.set('job:' + job.id, job.status)
        for (const render of renderRes.items) current.set('render:' + render.id, render.status)

        if (known.current) {
          for (const [key, state] of current) {
            const prev = known.current.get(key)
            if (prev === state) continue
            // prev 为空 = 这 4 秒里新出现的记录（可能直接就是失败），也要提示
            if (!TERMINAL.has(state) || (prev && TERMINAL.has(prev))) continue
            const name = key.slice(key.indexOf(':') + 1)
            if (key.startsWith('job:')) {
              const job = jobRes.items.find((j) => j.id === name)
              pushToast({
                kind: state === 'succeeded' ? 'ok' : 'err',
                title: state === 'succeeded' ? '生成完成' : '生成失败',
                text: `${job?.preset_id || '任务'} · ${name.slice(0, 12)}`,
                tab: 'jobs',
              })
            } else {
              const render = renderRes.items.find((r) => r.id === name)
              pushToast({
                kind: state === 'succeeded' ? 'ok' : 'err',
                title: state === 'succeeded' ? '成片导出完成' : '成片导出失败',
                text: `${render?.project_name || render?.project_id || ''} · ${name.slice(0, 12)}`,
                tab: 'renders',
              })
            }
          }
        }
        known.current = current
        if (!stopped) setJobsRefresh((v) => v + 0)
      } catch {
        // 网络抖动忽略
      }
    }
    void tick()
    const timer = window.setInterval(tick, 4000)
    return () => { stopped = true; window.clearInterval(timer) }
  }, [pushToast])

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent).detail as { kind?: 'ok' | 'err'; title?: string; text?: string } | undefined
      if (!detail) return
      pushToast({
        kind: detail.kind === 'err' ? 'err' : 'ok',
        title: detail.title || '提示',
        text: detail.text || '',
      })
    }
    window.addEventListener('dsh-toast', handler)
    return () => window.removeEventListener('dsh-toast', handler)
  }, [pushToast])

  const onJobCreated = (_job: Job) => {
    setJobsRefresh((v) => v + 1)
  }

  const ready = Boolean(status?.running)

  return (
    <div className="app">
      <aside className="rail">
        <div className="brand">
          <b>导演台</b>
          <span>ComfyUI Director Console</span>
        </div>

        <nav className="nav">
          <button className={tab === 'agent' ? 'active' : ''} onClick={() => setTab('agent')}>导演助手</button>
          <button className={tab === 'studio' ? 'active' : ''} onClick={() => setTab('studio')}>创作台</button>
          <button className={tab === 'projects' ? 'active' : ''} onClick={() => setTab('projects')}>项目</button>
          <button className={tab === 'edit' ? 'active' : ''} onClick={() => setTab('edit')}>剪辑</button>
          <button className={tab === 'assets' ? 'active' : ''} onClick={() => setTab('assets')}>资产</button>
          <button className={tab === 'renders' ? 'active' : ''} onClick={() => setTab('renders')}>
            成片
            {badges.renders > 0 && <span className="nav-badge">{badges.renders > 99 ? '99+' : badges.renders}</span>}
          </button>
          <button className={tab === 'jobs' ? 'active' : ''} onClick={() => setTab('jobs')}>
            任务
            {badges.jobs > 0 && <span className="nav-badge">{badges.jobs > 99 ? '99+' : badges.jobs}</span>}
          </button>
          <button className={tab === 'service' ? 'active' : ''} onClick={() => setTab('service')}>服务管家</button>
        </nav>

        <div className="rail-foot">
          <span>
            <span className={`status-dot ${ready ? (status?.mode === 'mock' ? 'mock' : 'on') : ''}`} />{' '}
            {ready ? (status?.mode === 'mock' ? '模拟模式' : 'ComfyUI 在线') : 'ComfyUI 离线'}
          </span>
          <span>{status?.mode ?? '—'} · {status?.base_url ?? '—'}</span>
          <span>v0.1 · H3 专版</span>
        </div>
      </aside>

      <div className="toast-wrap">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast ${toast.kind}`}
               onClick={() => { if (toast.tab) setTab(toast.tab) }}>
            <b>{toast.title}</b>
            <span>{toast.text}</span>
            <button className="ghost tiny"
                    onClick={(e) => { e.stopPropagation(); setToasts((prev) => prev.filter((x) => x.id !== toast.id)) }}>
              ×
            </button>
          </div>
        ))}
      </div>

      <main className="main">
        {tab === 'agent' && (
          <AgentPanel
            projectId={new URLSearchParams(window.location.search).get('project') || ''}
            onOpenProject={(projectId) => {
              const url = new URL(window.location.href)
              url.searchParams.set('project', projectId)
              window.history.replaceState({}, '', url)
              setTab('agent')
            }}
          />
        )}
        {tab === 'studio' && (
          <StudioPanel
            serviceReady={ready}
            onJobCreated={onJobCreated}
            onGoJobs={() => setTab('jobs')}
          />
        )}
        {tab === 'jobs' && <JobsPanel refreshKey={jobsRefresh} />}
        {tab === 'projects' && (
          <ProjectsPanel
            onEdit={(projectId) => {
              const url = new URL(window.location.href)
              url.searchParams.set('project', projectId)
              window.history.replaceState({}, '', url)
              setTab('edit')
            }}
          />
        )}
        {tab === 'edit' && (
          <EditPanel
            initialProjectId={new URLSearchParams(window.location.search).get('project') || undefined}
            onGoRenders={() => setTab('renders')}
          />
        )}
        {tab === 'renders' && (
          <RendersPanel
            onOpenProject={(projectId) => {
              const url = new URL(window.location.href)
              url.searchParams.set('project', projectId)
              window.history.replaceState({}, '', url)
              setTab('projects')
            }}
          />
        )}
        {tab === 'assets' && (
          <AssetsPanel
            onOpenProject={(projectId, shotId) => {
              const url = new URL(window.location.href)
              url.searchParams.set('project', projectId)
              if (shotId) url.searchParams.set('shot', shotId)
              window.history.replaceState({}, '', url)
              setTab('projects')
            }}
          />
        )}
        {tab === 'service' && <ServicePanel status={status} onRefresh={refreshStatus} />}
      </main>
    </div>
  )
}
