import { useEffect, useState } from 'react'
import { api } from '../api'
import { Markdown } from '../cite'
import UseCaseResult from '../components/UseCaseResult'

const EXAMPLES = [
  ['⚡ Impact: retire Oracle', 'What would be impacted if we retired Oracle as a vendor?'],
  ['📄 Summarize Customer Portal', 'Summarize the Customer Portal.'],
  ['🔍 Capabilities with no owner', 'Which capabilities have no owning department?'],
  ['🔐 SMS data flow', 'What happens to applicant data sent to the SMS gateway?'],
  ['🔗 Payment Gateway links', 'What does the Payment Gateway connect to?'],
]
const PILL = { answered: 'ok', refused: 'crit', abstained: 'warn', blocked_output: 'crit', retrieved: 'info', error: 'crit' }

export default function Ask() {
  const [mode, setMode] = useState('ask')              // 'ask' | 'usecase'
  // --- ask mode ---
  const [q, setQ] = useState('What would be impacted if we retired Oracle as a vendor?')
  const [res, setRes] = useState(null)
  const [loading, setLoading] = useState(false)
  // --- use-case mode ---
  const [list, setList] = useState([])
  const [ucId, setUcId] = useState('')
  const [spec, setSpec] = useState(null)
  const [demand, setDemand] = useState('')
  const [ucRes, setUcRes] = useState(null)
  const [ucLoading, setUcLoading] = useState(false)
  const [ucErr, setUcErr] = useState('')

  useEffect(() => { api.usecases().then(d => {
    const en = d.usecases.filter(u => u.enabled !== false)
    setList(en); if (en.length && !ucId) setUcId(en[0].id)
  }).catch(() => {}) }, [])
  useEffect(() => { if (ucId) api.usecase(ucId).then(setSpec).catch(() => setSpec(null)); else setSpec(null) }, [ucId])

  async function run() {
    setLoading(true); setRes(null)
    try { setRes(await api.ask(q)) } catch (e) { setRes({ status: 'error', answer: 'Request failed: ' + e }) }
    setLoading(false)
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

  return (
    <div className="wrap">
      <div className="view-head"><div>
        <div className="eyebrow">Ask &amp; assess</div>
        <h1>{mode === 'ask' ? 'What do you want to know?' : 'Submit a demand'}</h1>
        <p>{mode === 'ask'
          ? 'Ask in plain language. Answers are grounded in the ingested documents, with citations you can click.'
          : 'Submit a request against a use case. We answer what the knowledge base knows and list exactly what to provide for the rest.'}</p>
      </div></div>

      <div className="card composer">
        <div className="modes" role="group" aria-label="Mode">
          <button aria-pressed={mode === 'ask'} onClick={() => setMode('ask')}>Ask a question</button>
          <button aria-pressed={mode === 'usecase'} onClick={() => setMode('usecase')}>Submit a use case</button>
        </div>

        {mode === 'ask' ? (
          <>
            <textarea className="ta" value={q} onChange={(e) => setQ(e.target.value)} />
            <div className="composer-row">
              <button className="btn primary push" onClick={run} disabled={loading}>
                {loading ? 'Thinking…' : 'Run'}
              </button>
            </div>
            <div className="chips">{EXAMPLES.map(([l, ex]) => (
              <button key={l} className="chip" onClick={() => setQ(ex)}>{l}</button>
            ))}</div>
          </>
        ) : (
          <>
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
              <button className="btn primary push" onClick={submitUsecase} disabled={ucLoading}>
                {ucLoading ? 'Assessing…' : 'Submit'}
              </button>
            </div>
          </>
        )}
      </div>

      {mode === 'ask' && res && (
        <div className="answer">
          <div className="answer-meta">
            <span className={'pill ' + (PILL[res.status] || 'neutral')}>{res.status}</span>
            {res.route && <span className="route">routed via <b>{res.route.strategy}</b></span>}
            {res.citation_check && <span className="route">grounded <b>{String(res.citation_check.grounded)}</b></span>}
            {res.input_guard?.category && res.input_guard.category !== 'ok' &&
              <span className="pill crit">{res.input_guard.category}</span>}
          </div>
          <div className="card answer-body"><Markdown md={res.answer} /></div>
        </div>
      )}

      {mode === 'usecase' && ucErr && <div className="card" style={{ padding: 12, color: 'var(--crit)', marginTop: 14 }}>{ucErr}</div>}
      {mode === 'usecase' && ucRes && <UseCaseResult res={ucRes} />}
    </div>
  )
}
