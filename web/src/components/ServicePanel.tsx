import { useCallback, useEffect, useRef, useState } from 'react'
import { api, formatDuration } from '../api'
import type { ServiceStatus } from '../types'
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
      if (res && res.ok === false) {
        setError(res.message || '操作没有成功')
      } else {
        setMessage(res.message || '完成')
      }
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

  // 日志刷新后自动滚到底部（ComfyUI 启动时刷得很快，不跟到底就等于没看）
  const logRef = useRef<HTMLPreElement | null>(null)
  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [logs])

  const local = status?.local
  const health = local?.health || status?.health
  const device = health?.devices?.[0]
  const vram = device?.vram_total
    ? `${(device.vram_total / 1024 ** 3).toFixed(1)} GB（空闲 ${((device.vram_free || 0) / 1024 ** 3).toFixed(1)} GB）`
    : '—'
  const localHost = (local?.url || '').replace(/^https?:\/\//, '')

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
              ? `PID ${status.managed_pid} · 已运行 ${formatDuration(status.managed_uptime)}${status.managed_adopted ? ' · 接管自已有进程' : ''}`
              : status?.managed
                ? (local?.running
                  ? '外部启动（面板没有它的进程号，点「关闭」会按端口结束）'
                  : '由本面板托管（当前未运行）')
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

        {status?.managed && local?.running && !status?.managed_pid && (
          <div className="notice" style={{ marginTop: 12 }}>
            这个 ComfyUI 不是面板启动的（可能是桌面版、命令行或旧面板开的）。
            点「关闭」时面板会按端口 {localHost} 找到监听进程并结束它。
          </div>
        )}
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
          <pre className="logs" ref={logRef}>{logs || '（云端模式下没有本地日志）'}</pre>
        </div>
      )}

      <AISettingsPanel />

      <TTSPanel />

      <ASRPanel />

      <ModelCheckPanel />
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


function AISettingsPanel() {
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [proxy, setProxy] = useState('')
  const [visionModel, setVisionModel] = useState('')
  const [reasoningMode, setReasoningMode] = useState('auto')
  const [apiKey, setApiKey] = useState('')
  const [keyHint, setKeyHint] = useState('')
  const [overridden, setOverridden] = useState(false)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState('')

  useEffect(() => {
    api.aiSettings().then((s) => {
      setBaseUrl(s.base_url)
      setModel(s.model)
      setProxy(s.proxy || '')
      setReasoningMode(s.reasoning_mode || 'auto')
      setKeyHint(s.key_hint)
      setOverridden(s.overridden)
    }).catch(() => undefined)
  }, [])

  const payload = () => ({ base_url: baseUrl, model, proxy, vision_model: visionModel,
    reasoning_mode: reasoningMode, api_key: apiKey || undefined })

  const save = async () => {
    setBusy('save')
    setNote('')
    try {
      const s = await api.saveAiSettings(payload())
      setKeyHint(s.key_hint)
      setOverridden(true)
      setApiKey('')
      setNote('已保存，提示词助手立即生效')
    } catch (err) {
      setNote(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy('')
    }
  }

  const test = async () => {
    setBusy('test')
    setNote('')
    try {
      const r = await api.testAiSettings(payload())
      setNote(r.ok ? `连接正常（${r.latency_ms}ms，${r.model_count ?? 0} 个模型）` : `失败：${r.error}`)
    } catch (err) {
      setNote(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy('')
    }
  }

  const reset = async () => {
    setBusy('reset')
    try {
      await api.resetAiSettings()
      const s = await api.aiSettings()
      setBaseUrl(s.base_url)
      setModel(s.model)
      setProxy(s.proxy || '')
      setKeyHint(s.key_hint)
      setOverridden(s.overridden)
      setNote('已恢复配置文件默认值')
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="panel">
      <h2>
        <span>提示词助手</span>
        {overridden && <span className="badge">已覆盖配置文件</span>}
      </h2>
      <p className="hint">填自己的 OpenAI 兼容接口；留空 API Key 表示不修改已保存的 key。</p>
      <div className="field">
        <label><span>Base URL</span></label>
        <input value={baseUrl} placeholder="https://api.openai.com/v1"
               onChange={(e) => setBaseUrl(e.target.value)} />
      </div>
      <div className="field">
        <label><span>模型</span></label>
        <input value={model} placeholder="gpt-4o-mini / deepseek-chat"
               onChange={(e) => setModel(e.target.value)} />
      </div>
      <div className="field">
        <label><span>多模态模型（可选，带视频截图生成时用）</span></label>
        <input value={visionModel} placeholder="例如 qwen3-vl-plus"
               onChange={(e) => setVisionModel(e.target.value)} />
      </div>
      <div className="field">
        <label><span>思考模式（推理模型的思考内容怎么取）</span></label>
        <select value={reasoningMode} onChange={(e) => setReasoningMode(e.target.value)}>
          <option value="auto">自动（默认，有 reasoning_content 就显示）</option>
          <option value="deepseek">DeepSeek（思考放在 reasoning_content）</option>
          <option value="off">关闭思考（仅支持 enable_thinking 的模型）</option>
        </select>
        <p className="hint" style={{ marginTop: 6 }}>
          选 DeepSeek 后，等待时会先把思考过程流式显示出来，不用干等正文。
        </p>
      </div>
      <div className="field">
        <label><span>API Key{keyHint ? `（当前 ${keyHint}）` : ''}</span></label>
        <input type="password" value={apiKey} placeholder="留空表示不修改"
               onChange={(e) => setApiKey(e.target.value)} />
      </div>
      <div className="field">
        <label><span>代理（可选）</span></label>
        <input value={proxy} placeholder="http://127.0.0.1:1081"
               onChange={(e) => setProxy(e.target.value)} />
      </div>
      <div className="row-actions">
        <button className="primary" disabled={!baseUrl || busy === 'save'} onClick={() => void save()}>
          {busy === 'save' ? '保存中…' : '保存'}
        </button>
        <button disabled={busy === 'test'} onClick={() => void test()}>
          {busy === 'test' ? '测试中…' : '测试连接'}
        </button>
        <button className="ghost" disabled={busy === 'reset'} onClick={() => void reset()}>恢复默认</button>
      </div>
      {note && <div className="notice" style={{ marginTop: 8 }}>{note}</div>}
    </div>
  )
}


function TTSPanel() {
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('qwen-audio-3.0-tts-plus')
  const [voice, setVoice] = useState('longanlufeng')
  const [apiKey, setApiKey] = useState('')
  const [keyHint, setKeyHint] = useState('')
  const [proxy, setProxy] = useState('')
  const [voices, setVoices] = useState<Array<{ id: string; name: string }>>([])
  const [audioUrl, setAudioUrl] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState('')

  useEffect(() => {
    api.ttsSettings().then((s) => {
      const list = s.voices || []
      setBaseUrl(s.base_url)
      setModel(s.model)
      // 存下来的音色可能属于别的模型（切过模型就会这样），对不上就退回该模型的第一个
      setVoice(list.some((v) => v.id === s.voice) ? s.voice : (list[0]?.id || s.voice))
      setProxy(s.proxy || '')
      setKeyHint(s.key_hint)
      setVoices(list)
    }).catch(() => undefined)
  }, [])

  const changeModel = (next: string) => {
    setModel(next)
    // 换模型必须同时换音色：3.0-plus 只认 longanlufeng/longanlingxin，
    // 3.1 的 *_v3.1 音色配到 3.0 上会被服务端拒成 411
    api.ttsVoices(next).then((r) => {
      const list = r.items || []
      setVoices(list)
      setVoice(list[0]?.id || '')
    }).catch(() => { setVoices([]); setVoice('') })
  }

  const payload = () => ({ base_url: baseUrl, model, voice, proxy, api_key: apiKey || undefined })

  const save = async () => {
    setBusy('save')
    setNote('')
    try {
      const s = await api.saveTtsSettings(payload())
      setVoices(s.voices || [])
      setKeyHint(s.key_hint)
      setApiKey('')
      setNote('已保存')
    } catch (err) {
      setNote(err instanceof Error ? err.message : String(err))
    } finally { setBusy('') }
  }

  const test = async () => {
    setBusy('test')
    setNote('')
    try {
      const r = await api.testTts(payload())
      if (r.ok) {
        setAudioUrl(r.url || '')
        setNote(`试听成功（${r.duration}s）`)
      } else {
        setAudioUrl('')
        setNote(`失败：${r.error}`)
      }
    } catch (err) {
      setNote(err instanceof Error ? err.message : String(err))
    } finally { setBusy('') }
  }

  return (
    <div className="panel">
      <h2>
        <span>旁白配音（TTS）</span>
        {keyHint && <span className="badge">当前 {keyHint}</span>}
      </h2>
      <p className="hint">
        阿里云百炼 qwen-audio-3.0-tts-plus。Base URL 填控制台给的工作区域名，例如
        https://xxx.cn-beijing.maas.aliyuncs.com
      </p>
      <div className="field">
        <label><span>Base URL</span></label>
        <input value={baseUrl} placeholder="https://<workspace>.cn-beijing.maas.aliyuncs.com"
               onChange={(e) => setBaseUrl(e.target.value)} />
      </div>
      <div className="field">
        <label><span>API Key{keyHint ? `（当前 ${keyHint}）` : ''}</span></label>
        <input type="password" value={apiKey} placeholder="留空表示不修改"
               onChange={(e) => setApiKey(e.target.value)} />
      </div>
      <div className="field">
        <label><span>代理（可选，留空沿用提示词助手的代理）</span></label>
        <input value={proxy} placeholder="http://127.0.0.1:1081"
               onChange={(e) => setProxy(e.target.value)} />
      </div>
      <div className="row">
        <select value={model} onChange={(e) => changeModel(e.target.value)}>
          <option value="qwen-audio-3.0-tts-plus">qwen-audio-3.0-tts-plus</option>
          <option value="qwen-audio-3.1-tts-flash">qwen-audio-3.1-tts-flash</option>
        </select>
        <select className="grow" value={voice} onChange={(e) => setVoice(e.target.value)}>
          {voices.map((v) => <option key={v.id} value={v.id}>{v.name || v.id}</option>)}
          {!voices.length && <option value={voice}>{voice}</option>}
        </select>
      </div>
      <div className="row-actions">
        <button className="primary" disabled={!baseUrl || busy === 'save'} onClick={() => void save()}>
          {busy === 'save' ? '保存中…' : '保存'}
        </button>
        <button disabled={busy === 'test'} onClick={() => void test()}>
          {busy === 'test' ? '合成中…' : '试听'}
        </button>
      </div>
      {note && <div className="notice" style={{ marginTop: 8 }}>{note}</div>}
      {audioUrl && (
        <audio className="tts-audio" src={audioUrl} controls autoPlay />
      )}
    </div>
  )
}


function ASRPanel() {
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('qwen-audio-3.0-asr-flash')
  const [proxy, setProxy] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [keyHint, setKeyHint] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.asrSettings().then((s) => {
      setBaseUrl(s.base_url)
      setModel(s.model)
      setProxy(s.proxy || '')
      setKeyHint(s.key_hint)
    }).catch(() => undefined)
  }, [])

  const save = async () => {
    setBusy(true)
    setNote('')
    try {
      const s = await api.saveAsrSettings({ base_url: baseUrl, model, proxy, api_key: apiKey || undefined })
      setKeyHint(s.key_hint)
      setApiKey('')
      setNote('已保存')
    } catch (err) {
      setNote(err instanceof Error ? err.message : String(err))
    } finally { setBusy(false) }
  }

  const testAsr = async () => {
    setBusy(true)
    setNote('正在合成测试语音并转写…')
    try {
      const r = await api.testAsr()
      if (r.ok) {
        setNote(`转写成功：${r.text}${r.match ? '（内容匹配）' : '（内容与预期不同，但接口可用）'}`)
      } else {
        setNote(`失败（${r.stage === 'tts' ? '生成语音' : '转写'}）：${r.error}`)
      }
    } catch (err) {
      setNote(err instanceof Error ? err.message : String(err))
    } finally { setBusy(false) }
  }

  return (
    <div className="panel">
      <h2>
        <span>语音转写（ASR）</span>
        {keyHint && <span className="badge">当前 {keyHint}</span>}
      </h2>
      <p className="hint">
        没有旁白、但镜头里有人说话时，用这里的模型把口播转成字幕。
        模型必须在当前工作区可用（例如 qwen3-asr-flash 或你控制台里开通的转写模型）。
      </p>
      <div className="field">
        <label><span>Base URL</span></label>
        <input value={baseUrl} placeholder="https://<workspace>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
               onChange={(e) => setBaseUrl(e.target.value)} />
      </div>
      <div className="field">
        <label><span>API Key{keyHint ? `（当前 ${keyHint}）` : ''}</span></label>
        <input type="password" value={apiKey} placeholder="留空表示沿用提示词助手的 key"
               onChange={(e) => setApiKey(e.target.value)} />
      </div>
      <div className="field">
        <label><span>转写模型</span></label>
        <input value={model} placeholder="qwen-audio-3.0-asr-flash"
               onChange={(e) => setModel(e.target.value)} />
      </div>
      <div className="field">
        <label><span>代理（可选）</span></label>
        <input value={proxy} placeholder="留空沿用提示词助手的代理"
               onChange={(e) => setProxy(e.target.value)} />
      </div>
      <div className="row-actions">
        <button className="primary" disabled={!baseUrl || busy} onClick={() => void save()}>
          {busy ? '保存中…' : '保存'}
        </button>
        <button disabled={busy || !baseUrl} onClick={() => void testAsr()}>
          {busy ? '处理中…' : '测试转写'}
        </button>
      </div>
      {note && <div className="notice" style={{ marginTop: 8 }}>{note}</div>}
    </div>
  )
}
