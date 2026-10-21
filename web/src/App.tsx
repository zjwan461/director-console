import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import type { Job, ServiceStatus } from './types'
import ServicePanel from './components/ServicePanel'
import StudioPanel from './components/StudioPanel'
import JobsPanel from './components/JobsPanel'
import ProjectsPanel from './components/ProjectsPanel'
import AssetsPanel from './components/AssetsPanel'
import RendersPanel from './components/RendersPanel'

type Tab = 'studio' | 'projects' | 'assets' | 'renders' | 'jobs' | 'service'

const TAB_KEYS: Tab[] = ['studio', 'projects', 'assets', 'renders', 'jobs', 'service']

function initialTab(): Tab {
  const fromUrl = new URLSearchParams(window.location.search).get('tab')
  return (TAB_KEYS as string[]).includes(fromUrl || '') ? (fromUrl as Tab) : 'studio'
}

export default function App() {
  const [tab, setTabState] = useState<Tab>(initialTab)
  const [status, setStatus] = useState<ServiceStatus | null>(null)
  const [jobsRefresh, setJobsRefresh] = useState(0)

  const setTab = (next: Tab) => {
    setTabState(next)
    const url = new URL(window.location.href)
    if (next === 'studio') url.searchParams.delete('tab')
    else url.searchParams.set('tab', next)
    window.history.replaceState({}, '', url)
  }

  const refreshStatus = useCallback(() => {
    api.serviceStatus().then(setStatus).catch(() => setStatus(null))
  }, [])

  useEffect(() => {
    refreshStatus()
    const timer = setInterval(refreshStatus, 5000)
    return () => clearInterval(timer)
  }, [refreshStatus])

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
          <button className={tab === 'studio' ? 'active' : ''} onClick={() => setTab('studio')}>创作台</button>
          <button className={tab === 'projects' ? 'active' : ''} onClick={() => setTab('projects')}>项目</button>
          <button className={tab === 'assets' ? 'active' : ''} onClick={() => setTab('assets')}>资产</button>
          <button className={tab === 'renders' ? 'active' : ''} onClick={() => setTab('renders')}>成片</button>
          <button className={tab === 'jobs' ? 'active' : ''} onClick={() => setTab('jobs')}>任务</button>
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

      <main className="main">
        {tab === 'studio' && (
          <StudioPanel
            serviceReady={ready}
            onJobCreated={onJobCreated}
            onGoJobs={() => setTab('jobs')}
          />
        )}
        {tab === 'jobs' && <JobsPanel refreshKey={jobsRefresh} />}
        {tab === 'projects' && <ProjectsPanel />}
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
