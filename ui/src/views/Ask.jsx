import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { Markdown } from '../cite'
import { useChats } from '../chats'
import UseCaseResult from '../components/UseCaseResult'
import Graph from '../components/Graph'

const EXAMPLES = [
  ['⚡ Impact: retire Oracle', 'What would be impacted if we retired Oracle as a vendor?'],
  ['📄 Summarize Customer Portal', 'Summarize the Customer Portal.'],
  ['🔍 Capabilities with no owner', 'Which capabilities have no owning department?'],
  ['🔐 SMS data flow', 'What happens to applicant data sent to the SMS gateway?'],
  ['🔗 Payment Gateway links', 'What does the Payment Gateway connect to?'],
]
const PILL = { answered: 'ok', refused: 'crit', abstained: 'warn', blocked_output: 'crit', retrieved: 'info', error: 'crit' }

export default function Ask() {
  const { activeChatId, setActiveChatId, refreshChats } = useChats()
  const [mode, setMode] = useState('ask')              // 'ask' | 'usecase'
  const [q, setQ] = useState('')
  const [msgs, setMsgs] = useState([])
  const [loading, setLoading] = useState(false)
  const endRef = useRef(null)
  const loadedRef = useRef(undefined)                  // guards the load effect
  // --- use-case mode ---
  const [list, setList] = useState([])
  const [ucId, setUcId] = useState('')
  const [spec, setSpec] = useState(null)
  const [demand, setDemand] = useState('')
  const [ucRes, setUcRes] = useState(null)
  const [ucLoading, setUcLoading] = useState(false)
  const [ucErr, setUcErr] = useState('')

  // Load / reset the conversation when the sidebar changes the active chat.
  useEffect(() => {
    if (activeChatId === loadedRef.current) return
    loadedRef.current = activeChatId
    if (!activeChatId) { setMsgs([]); return }
    setMode('ask')
    api.chatGet(activeChatId).then(c => setMsgs(c.messages || [])).catch(() => {})
  }, [activeChatId])

  useEffect(() => { api.usecases().then(d => {
    const en = d.usecases.filter(u => u.enabled !== false)
    setList(en); if (en.length && !ucId) setUcId(en[0].id)
  }).catch(() => {}) }, [])
  useEffect(() => { if (ucId) api.usecase(ucId).then(setSpec).catch(() => setSpec(null)); else setSpec(null) }, [ucId])
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs, loading])

  async function saveChat(messages) {
    try {
      const r = await api.chatSave({ id: activeChatId, messages: messages.map(m => ({ role: m.role, content: m.content, meta: m.meta })) })
      if (!activeChatId) { loadedRef.current = r.id; setActiveChatId(r.id) }
      refreshChats()
    } catch { /* best-effort */ }
  }

  async function send() {
    const text = q.trim()
    if (!text || loading) return
    const base = msgs
    const history = base.filter(m => m.role !== 'bot' || m.content).map(m => ({
      role: m.role === 'user' ? 'user' : 'assistant',
      content: m.role === 'user' ? m.content : (m.meta?.answer ?? m.content),
    }))
    const withUser = [...base, { role: 'user', content: text }]
    setMsgs(withUser); setQ(''); setLoading(true)
    try {
      const res = await api.ask(text, history)
      const withBot = [...withUser, { role: 'bot', content: res.answer, meta: { ...res, answer: res.answer } }]
      setMsgs(withBot); saveChat(withBot)
    } catch (e) {
      setMsgs([...withUser, { role: 'bot', content: 'Request failed: ' + e, meta: { status: 'error' } }])
    }
    setLoading(false)
  }

  function onKey(e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }
  function onUcFile(e) {
    const f = e.target.files?.[0]; if (!f) return
    const r = new FileReader(); r.onload = () => setDemand(String(r.result || '').trim()); r.readAsText(f)
  }
  async function submitUsecase() {
    setUcErr(''); setUcRes(null)
    if (!ucId) { setUcErr('Choose a use case first.'); return }
    if (!demand.trim()) { setUcErr('Describe the demand or request.'); return }
    const field = spec?.input?.batch_text_field || 'demand'
    setUcLoading(true)
    try { setUcRes(await api.runUsecase(ucId, { items: [{ demand_no: 'D-1', [field]: demand.trim() }], k: 6 })) }
    catch (e) { setUcErr(String(e).replace('Error: ', '')) }
    setUcLoading(false)
  }

  const modeToggle = (
    <div className="modes" role="group" aria-label="Mode">
      <button aria-pressed={mode === 'ask'} onClick={() => setMode('ask')}>Ask a question</button>
      <button aria-pressed={mode === 'usecase'} onClick={() => setMode('usecase')}>Submit a use case</button>
    </div>
  )

  if (mode === 'usecase') {
    return (
      <div className="wrap">
        <div className="view-head"><div>
          <div className="eyebrow">Ask &amp; assess</div>
          <h1>Submit a demand</h1>
          <p>Submit a request against a use case. We answer what the knowledge base knows and list exactly what to provide for the rest.</p>
        </div></div>
        <div className="card composer">
          {modeToggle}
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 10 }}>
            <select value={ucId} onChange={e => setUcId(e.target.value)} style={{ minWidth: 240 }}>
              <option value="">— select a use case —</option>
              {list.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}
            </select>
            {spec?.validation?.enabled && <span className="pill info">validation gate</span>}
            {spec && <span className="pill neutral">{spec.stages.length} stage(s)</span>}
          </div>
          {spec?.description && <p className="meta" style={{ marginBottom: 10 }}>{spec.description}</p>}
          <textarea className="ta" value={demand} onChange={e => setDemand(e.target.value)}
            placeholder={spec?.input?.placeholder || 'Describe the demand or change request in plain language…'} />
          <div className="composer-row">
            <label className="attach">Upload file<input type="file" accept=".txt,.md,.csv" hidden onChange={onUcFile} /></label>
            <button className="btn primary push" onClick={submitUsecase} disabled={ucLoading}>{ucLoading ? 'Assessing…' : 'Submit'}</button>
          </div>
        </div>
        {ucErr && <div className="card" style={{ padding: 12, color: 'var(--crit)', marginTop: 14 }}>{ucErr}</div>}
        {ucRes && <UseCaseResult res={ucRes} />}
      </div>
    )
  }

  // ---- ask mode: full-height chat, composer pinned at bottom ----
  return (
    <div className="wrap chat">
      <div className="view-head"><div>
        <div className="eyebrow">Ask &amp; assess</div>
        <h1>What do you want to know?</h1>
      </div></div>

      <div className="thread">
        {msgs.map((m, i) => (
          <div key={i} className={'turn ' + (m.role === 'user' ? 'user' : 'bot')}>
            <div className={'bubble' + (m.meta?.graph ? ' wide' : '')}>
              {m.role === 'bot' && m.meta && (
                <div className="answer-meta">
                  <span className={'pill ' + (PILL[m.meta.status] || 'neutral')}>{m.meta.status}</span>
                  {m.meta.route && <span className="route">via <b>{m.meta.route.strategy}</b></span>}
                  {m.meta.citation_check && <span className="route">grounded <b>{String(m.meta.citation_check.grounded)}</b></span>}
                </div>
              )}
              {m.role === 'bot' && m.meta?.search_question && m.meta.search_question !== msgs[i - 1]?.content &&
                <div className="rewrite">interpreted as: “{m.meta.search_question}”</div>}
              {m.role === 'bot' ? <Markdown md={m.content} /> : m.content}
              {m.role === 'bot' && m.meta?.graph && (
                <div className="ans-graph">
                  <div className="ans-graph-cap">
                    {m.meta.graph.template === 'generated' ? (
                      <>
                        <span className="pill warn" style={{ marginRight: 6 }}>generated query</span>
                        <span className={'pill ' + (m.meta.graph.verified ? 'ok' : 'crit')} style={{ marginRight: 8 }}>
                          {m.meta.graph.verified ? '✓ verified' : '⚠ unverified'}
                        </span>
                      </>
                    ) : (
                      <span className="pill info" style={{ marginRight: 8 }}>via {m.meta.graph.template} template</span>
                    )}
                    {m.meta.graph.summary}
                  </div>
                  {m.meta.graph.nodes?.length > 1 &&
                    <Graph nodes={m.meta.graph.nodes} edges={m.meta.graph.edges} height={300} mini={false} />}
                  {m.meta.graph.facts && (
                    <details className="explain">
                      <summary>{m.meta.graph.query ? 'Query & results — verify' : 'Graph facts used'}</summary>
                      <pre>{m.meta.graph.facts}</pre>
                    </details>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && <div className="turn bot pending"><div className="bubble"><span className="typing"><i /><i /><i /></span></div></div>}
        <div ref={endRef} />
      </div>

      <div className="card composer">
        {modeToggle}
        <textarea className="ta" value={q} onChange={e => setQ(e.target.value)} onKeyDown={onKey}
          placeholder={msgs.length ? 'Ask a follow-up…' : 'Ask about the architecture…'} />
        <div className="composer-row">
          <button className="btn primary push" onClick={send} disabled={loading}>
            {loading ? 'Thinking…' : (msgs.length ? 'Send' : 'Ask')}
          </button>
        </div>
        {msgs.length === 0 && <div className="chips">{EXAMPLES.map(([l, ex]) => (
          <button key={l} className="chip" onClick={() => setQ(ex)}>{l}</button>
        ))}</div>}
      </div>
    </div>
  )
}
