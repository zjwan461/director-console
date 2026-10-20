import { useCallback, useEffect, useState } from 'react'
import { api, formatDuration, timeAgo } from '../api'
import type { Job, ServiceStatus } from '../types'
import ModelCheckPanel from './ModelCheckPanel'

interface Props {
  status: ServiceStatus | null
  onRefresh: () => void
}

interface ProbeResult {
  ok: boolean
  error?: string
  latency_ms?: number
  system?: Record<string, unknown>
  devices?: Array<{ name?: string; vram_total?: number; vram_free?: number }>
}

export default function ServicePanel({ status, onRefresh }: Props) {
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [logs, setLogs] = useState('')
  const [showLogs, setShowLogs] = useState(false)

  const act = async (name: string, fn: () => Promise<{ ok: boolean; message: string }>) => {
    setBusy(name)
    setError('')
    setMessage('')
    try {
      const res = await fn()
      setMessage(res.message || '完成')
      onRefresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy('')
    }
  }

  const loadLogs = useCallback(async () => {
    try {
      const res = await api.serviceLogs(300)
      setLogs(res.text || '（暂无日志）')
    } catch (err) {
      setLogs(`读取失败：${err instanceof Error ? err.message : String(err)}`)
    }
  }, [])

  useEffect(() => {
    if (!showLogs) return
    void loadLogs()
    const timer = setInterval(() => void loadLogs(), 5000)
    return () => clearInterval(timer)
  }, [showLogs, loadLogs])

  const local = status?.local
  const health = local?.health || status?.health
  const device = health?.devices?.[0]
  const vram = device?.vram_total
    ? `${(device.vram_total / 1024 ** 3).toFixed(1)} GB（空闲 ${((device.vram_free || 0) / 1024 ** 3).toFixed(1)} GB）`
    : '—'

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>服务管家</h1>
          <p>ComfyUI 可以在本机、局域网，也可以是完全云端的服务——填地址就能用。</p>
        </div>
        <button className="ghost" onClick={onRefresh}>刷新状态</button>
      </div>

      <ConnectionSettings status={status} onSaved={() => { onRefresh(); setMessage('连接设置已保存') }} />

      <div className="panel">
        <h2>
          <span>
            <span className={`status-dot ${local?.running ? (status?.mode === 'mock' ? 'mock' : 'on') : ''}`} />{' '}
            {local?.running ? '本地 ComfyUI 已连接' : '本地 ComfyUI 未连接'}
          </span>
          <span className="badge">本机 {local?.url ?? ''}</span>
        </h2>

        <dl className="kv">
          <dt>本地地址</dt><dd>{local?.url ?? status?.base_url ?? '—'}</dd>
          <dt>当前会话</dt><dd>{modeLabel(status?.mode)}</dd>
          <dt>托管进程</dt>
          <dd>
            {status?.managed_pid
              ? `PID ${status.managed_pid} · 已运行 ${formatDuration(status.managed_uptime)}`
              : status?.managed
                ? '由本面板托管（当前未运行）'
                : '外部托管（面板不启动进程）'}
          </dd>
          {status?.workdir && (<><dt>工作目录</dt><dd>{status.workdir}</dd></>)}
          <dt>显卡</dt><dd>{device?.name ?? '—'}</dd>
          <dt>显存</dt><dd>{vram}</dd>
          <dt>版本</dt><dd>{String(health?.system?.comfyui_version ?? '—')}</dd>
          <dt>延迟</dt><dd>{health?.latency_ms != null ? `${health.latency_ms} ms` : '—'}</dd>
          {health?.error && (<><dt>错误</dt><dd style={{ color: 'var(--err)' }}>{health.error}</dd></>)}
        </dl>

        {status && status.mode !== 'local' && status.mode !== 'ssh' && (
          <div className="notice" style={{ marginTop: 10 }}>
            当前任务走「{modeLabel(status.mode)}」，这张卡只反映本机 ComfyUI 是否在线。
            想让面板托管启停，把上面的连接方式改成「本机」。
          </div>
        )}

        <div className="row-actions">
          <button
            className="primary"
            disabled={!!busy || !status?.managed}
            onClick={() => void act('start', api.serviceStart)}
          >
            {busy === 'start' ? <><span className="spin" /> 启动中</> : '一键启动'}
          </button>
          <button disabled={!!busy || !status?.managed} onClick={() => void act('stop', api.serviceStop)}>
            {busy === 'stop' ? '停止中…' : '关闭'}
          </button>
          <button disabled={!!busy || !status?.managed} onClick={() => void act('restart', api.serviceRestart)}>
            {busy === 'restart' ? '重启中…' : '重启'}
          </button>
          <button disabled={!!busy} onClick={() => void act('free', api.serviceFree)}>释放显存</button>
          <button className="ghost" onClick={() => setShowLogs((v) => !v)}>
            {showLogs ? '收起日志' : '查看日志'}
          </button>
          {status?.advanced_panel && (
            <a href={status.advanced_panel} target="_blank" rel="noreferrer">
              <button className="ghost">高级模式（旧面板）</button>
            </a>
          )}
          {status?.comfy_web && (
            <a href={status.comfy_web} target="_blank" rel="noreferrer">
              <button className="ghost">打开 ComfyUI</button>
            </a>
          )}
        </div>

        {!status?.managed && status?.mode === 'external' && (
          <div className="notice" style={{ marginTop: 12 }}>
            云端 / 外部模式：面板不启动也不关闭对方的进程，只负责提交任务和取结果。
            服务没开时，请到云平台控制台启动。
          </div>
        )}
        {message && <div className="notice" style={{ marginTop: 12 }}>{message}</div>}
        {error && <div className="notice err" style={{ marginTop: 12 }}>{error}</div>}
      </div>

      {showLogs && (
        <div className="panel">
          <h2>ComfyUI 日志 <button className="ghost" onClick={() => void loadLogs()}>刷新</button></h2>
          <pre className="logs">{logs || '（云端模式下没有本地日志）'}</pre>
        </div>
      )}

      <ModelCheckPanel />

      <div className="panel">
        <h2>最近的失败任务</h2>
        <FailureList />
      </div>
    </div>
  )
}

function modeLabel(mode?: string): string {
  return {
    external: '云端 / 外部（只连接）',
    local: '本机（面板启动进程）',
    ssh: '远程机（SSH 启停）',
    mock: '模拟（不出真片）',
  }[mode || ''] || mode || '—'
}

function ConnectionSettings({ status, onSaved }: { status: ServiceStatus | null; onSaved: () => void }) {
  const stored = status?.settings
  const [mode, setMode] = useState(stored?.mode || 'external')
  const [url, setUrl] = useState(stored?.base_url || '')
  const [token, setToken] = useState('')
  const [tokenDirty, setTokenDirty] = useState(false)
  const [result, setResult] = useState<ProbeResult | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')

  useEffect(() => {
    // 独立拉一次设置，避免状态轮询还没回来时表单先渲染成默认值
    api.comfySettings().then((s) => {
      setMode(s.mode)
      setUrl(s.base_url === 'mock://' ? '' : s.base_url)
    }).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!stored) return
    setMode(stored.mode)
    setUrl(stored.base_url === 'mock://' ? '' : stored.base_url)
  }, [stored?.mode, stored?.base_url])

  const test = async () => {
    setBusy('test')
    setError('')
    setResult(null)
    setSaved('')
    try {
      const res = await api.testComfy(url, tokenDirty ? token : undefined)
      setResult(res)
    } catch (err) {
      setResult({ ok: false, error: err instanceof Error ? err.message : String(err) })
    } finally {
      setBusy('')
    }
  }

  const save = async () => {
    setBusy('save')
    setError('')
    setSaved('')
    try {
      await api.saveComfySettings(mode, url, tokenDirty ? token : undefined)
      setToken('')
      setTokenDirty(false)
      setSaved('已保存，正在使用新地址')
      onSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy('')
    }
  }

  const reset = async () => {
    setBusy('reset')
    setError('')
    setSaved('')
    try {
      const res = await api.resetComfySettings()
      setMode(res.mode)
      setUrl(res.base_url)
      setToken('')
      setTokenDirty(false)
      setSaved('已恢复 config.yaml 的默认连接')
      onSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="panel">
      <h2>
        <span>ComfyUI 连接</span>
        {stored?.overridden && <span className="badge">已覆盖配置文件</span>}
      </h2>

      <div className="form">
        <div className="field">
          <label><span>连接方式</span></label>
          <div className="chips">
            {[
              ['external', '云端 / 外部'],
              ['local', '本机'],
              ['ssh', '远程机 (SSH)'],
              ['mock', '模拟'],
            ].map(([value, label]) => (
              <button
                key={value}
                className={`chip ${mode === value ? 'active' : ''}`}
                onClick={() => setMode(value)}
              >
                {label}
              </button>
            ))}
          </div>
          <span className="helper">
            {mode === 'external'
              ? '只填地址，不启动进程；适合 RunPod / 云主机 / 别人已经跑着的 ComfyUI。'
              : mode === 'local'
                ? '面板在本机拉起 ComfyUI 进程，用 config.yaml 里的 workdir/python。'
                : mode === 'ssh'
                  ? '面板通过 SSH 在远程机执行启动/停止命令，健康检查仍走上方的地址。'
                  : '不出真片，3 秒返回占位产物，用来验证界面与流程。'}
          </span>
        </div>

        <div className="field">
          <label><span>ComfyUI 地址</span></label>
          <input
            placeholder="https://xxxx-8188.proxy.example.com 或 http://192.168.1.20:8188"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
          <span className="helper">不带 http:// 也能识别；请填能直接访问 8188 的根地址，不要带 /api。</span>
        </div>

        <div className="field">
          <label>
            <span>访问令牌（可选）</span>
            {stored?.token_set && <span className="meta">已保存 {stored.token_hint}</span>}
          </label>
          <input
            type="password"
            placeholder={stored?.token_set ? '留空 = 不修改；输入新值则覆盖' : 'Bearer token / user:password / Basic xxx'}
            value={token}
            onChange={(e) => { setToken(e.target.value); setTokenDirty(true) }}
          />
          <span className="helper">裸 token 会作为 Bearer；含冒号的 user:password 会转成 Basic。</span>
        </div>

        <div className="row-actions">
          <button className="primary" disabled={busy !== '' || !url.trim()} onClick={() => void test()}>
            {busy === 'test' ? <><span className="spin" /> 测试中</> : '测试连接'}
          </button>
          <button disabled={busy !== ''} onClick={() => void save()}>
            {busy === 'save' ? '保存中…' : '保存并应用'}
          </button>
          <button className="ghost" disabled={busy !== ''} onClick={() => void reset()}>恢复配置文件默认</button>
        </div>

        {result && (
          <div className={`notice ${result.ok ? '' : 'err'}`}>
            {result.ok ? (
              <>
                连接成功 · {result.latency_ms ?? 0} ms
                {result.devices?.[0]?.name ? ` · ${result.devices[0].name}` : ''}
                {result.system?.comfyui_version ? ` · ComfyUI ${String(result.system.comfyui_version)}` : ''}
              </>
            ) : `连接失败：${result.error || '未知错误'}`}
          </div>
        )}
        {error && <div className="notice err">{error}</div>}
        {saved && <div className="notice">{saved}</div>}
      </div>
    </div>
  )
}

function FailureList() {
  const [jobs, setJobs] = useState<Job[]>([])
  useEffect(() => {
    const load = () => {
      api.jobs(30).then((res) => setJobs(res.items.filter((j) => j.status === 'failed'))).catch(() => undefined)
    }
    load()
    const timer = setInterval(load, 5000)
    return () => clearInterval(timer)
  }, [])

  if (!jobs.length) return <div className="empty">没有失败任务，一切正常。</div>
  return (
    <div className="job-list">
      {jobs.slice(0, 5).map((job) => (
        <div className="job" key={job.id}>
          <div className="body">
            <div className="title"><b>{job.preset_id}</b><span className="badge err">失败</span><span className="msg">{timeAgo(job.created_at)}</span></div>
            <div className="err">{job.error || job.message || '未知错误'}</div>
          </div>
        </div>
      ))}
    </div>
  )
}
