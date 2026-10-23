import { useState } from 'react'

export interface PromptDraft {
  title: string
  system: string
  user: string
  framesAvailable: boolean
  frames: number
  withFrames: boolean
  userReadOnly?: boolean
  note?: string
  error?: string
  framesUrls?: string[]
  outline?: string
  withOutline?: boolean
  outlineBusy?: boolean
}

interface Props {
  draft: PromptDraft
  busy?: boolean
  onCancel: () => void
  onConfirm: (payload: {
    system: string; user: string; frames: number; framePicks: number[]; outline: string
  }) => void
  onGenerateOutline?: () => Promise<void>
}

export default function PromptDialog({ draft, busy, onCancel, onConfirm, onGenerateOutline }: Props) {
  const [system, setSystem] = useState(draft.system)
  const [user, setUser] = useState(draft.user)
  const [withFrames, setWithFrames] = useState(draft.withFrames)
  const allFrames = draft.framesUrls || []
  const [picked, setPicked] = useState<number[]>(
    () => allFrames.slice(0, Math.max(1, draft.frames || 3)).map((_, i) => i),
  )

  const [withOutline, setWithOutline] = useState(Boolean(draft.withOutline))
  const [outline, setOutline] = useState(draft.outline || '')

  const frames = withFrames ? picked.length : 0
  const edited = system !== draft.system || user !== draft.user

  return (
    <div className="picker-overlay" onClick={() => !busy && onCancel()}>
      <div className="picker prompt-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="picker-head">
          <b>{draft.title}</b>
          <button className="ghost tiny" onClick={onCancel} disabled={busy}>关闭</button>
        </div>

        <div className="prompt-dialog-body">
          {draft.error && <div className="notice err">{draft.error}</div>}

          <label className="field">
            <span>系统提示词（角色与规则）</span>
            <textarea value={system} onChange={(e) => setSystem(e.target.value)} rows={4} spellCheck={false} />
          </label>

          <label className="field">
            <span>本次输入（镜头信息 / 字数预算）</span>
            <textarea value={user} rows={9} spellCheck={false}
                      readOnly={draft.userReadOnly}
                      style={draft.userReadOnly ? { opacity: .75 } : undefined}
                      onChange={(e) => setUser(e.target.value)} />
          </label>
          {draft.note && <p className="hint">{draft.note}</p>}

          <div className="row" style={{ alignItems: 'center', gap: 10 }}>
            <label className="check" style={{ margin: 0 }}>
              <input type="checkbox" checked={withFrames} disabled={!draft.framesAvailable}
                     onChange={(e) => setWithFrames(e.target.checked)} />
              附带镜头截图
            </label>
            {draft.framesAvailable ? (
              <>
                <button className="ghost tiny" disabled={!withFrames}
                        onClick={() => setPicked(allFrames.map((_, i) => i))}>全选</button>
                <button className="ghost tiny" disabled={!withFrames || !picked.length}
                        onClick={() => setPicked([])}>清空</button>
              </>
            ) : (
              <span className="meta">这个镜头还没有视频，无法截图</span>
            )}
            {frames > 0 && <span className="meta">本次发送 {frames} 张</span>}
          </div>

          {draft.framesAvailable && allFrames.length > 0 && (
            <div className={`prompt-frames ${withFrames ? '' : 'off'}`}>
              {allFrames.map((url, index) => {
                const on = withFrames && picked.includes(index)
                return (
                  <figure key={url} className={on ? 'on' : 'off'}
                          onClick={() => {
                            if (!withFrames) return
                            setPicked((prev) => prev.includes(index)
                              ? prev.filter((i) => i !== index)
                              : [...prev, index].sort((a, b) => a - b))
                          }}
                          title={on ? '点击取消这一张' : '点击加入这一张'}>
                    <img src={url} alt={`截图 ${index + 1}`} />
                    <figcaption>{index + 1}{on ? ' ✓' : ''}</figcaption>
                  </figure>
                )
              })}
            </div>
          )}
          {draft.framesAvailable && !(draft.framesUrls?.length || 0) && (
            <p className="hint">截图会在点「发送给 AI」时按张数抽取。</p>
          )}

          <div className="prompt-outline">
            <div className="row" style={{ alignItems: 'center', gap: 8 }}>
              <label className="check" style={{ margin: 0 }}>
                <input type="checkbox" checked={withOutline}
                       onChange={(e) => setWithOutline(e.target.checked)} />
                带上全片大纲（更连贯）
              </label>
              {onGenerateOutline && (
                <button className="ghost tiny" disabled={draft.outlineBusy}
                        onClick={() => void onGenerateOutline()}>
                  {draft.outlineBusy ? <><span className="spin" /> 生成中</> : outline ? '重新生成大纲' : '生成大纲'}
                </button>
              )}
            </div>
            <textarea value={outline} rows={4} spellCheck={false}
                      placeholder="还没有大纲。点「生成大纲」让 AI 根据所有镜头写一份，也可以自己填。"
                      onChange={(e) => setOutline(e.target.value)} />
            {withOutline && !outline.trim() && (
              <p className="hint" style={{ color: '#facc15' }}>勾了但大纲是空的，本次不会带上大纲。</p>
            )}
          </div>

          <p className="hint">
            这些就是实际发送给 AI 的内容，可以直接改。改过的提示词只影响这一次生成。
          </p>
        </div>

        <div className="prompt-dialog-foot">
          <button className="ghost" onClick={() => { setSystem(draft.system); setUser(draft.user); setWithFrames(draft.withFrames) }}
                  disabled={busy || !edited}>
            恢复默认
          </button>
          <span style={{ flex: 1 }} />
          <button className="ghost" onClick={onCancel} disabled={busy}>取消</button>
          <button className="primary" disabled={busy || !system.trim() || !user.trim()}
                  onClick={() => onConfirm({
                    system, user, frames,
                    framePicks: withFrames ? picked : [],
                    outline: withOutline ? outline : '',
                  })}>
            {busy ? '生成中…' : '发送给 AI'}
          </button>
        </div>
      </div>
    </div>
  )
}
