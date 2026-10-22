import { useState } from 'react'
import { api } from '../api'
import { Markdown } from '../cite'

const EXAMPLES = [
  ['⚡ Impact: retire Oracle', 'What would be impacted if we retired Oracle as a vendor?'],
  ['📄 Summarize Customer Portal', 'Summarize the Customer Portal.'],
  ['🔍 Capabilities with no owner', 'Which capabilities have no owning department?'],
  ['🔐 SMS data flow', 'What happens to applicant data sent to the SMS gateway?'],
  ['🔗 Payment Gateway links', 'What does the Payment Gateway connect to?'],
]
const PILL = { answered: 'ok', refused: 'crit', abstained: 'warn', blocked_output: 'crit', retrieved: 'info', error: 'crit' }

export default function Ask() {
  const [q, setQ] = useState('What would be impacted if we retired Oracle as a vendor?')
  const [res, setRes] = useState(null)
  const [loading, setLoading] = useState(false)

  async function run() {
    setLoading(true); setRes(null)
    try { setRes(await api.ask(q)) } catch (e) { setRes({ status: 'error', answer: 'Request failed: ' + e }) }
    setLoading(false)
  }

  return (
    <div className="wrap">
      <div className="view-head"><div>
        <div className="eyebrow">Ask &amp; assess</div>
        <h1>What do you want to know?</h1>
        <p>Ask in plain language. Answers are grounded in the ingested documents, with citations you can click.</p>
      </div></div>
      <div className="card composer">
        <textarea className="ta" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="composer-row">
          <button className="btn primary push" onClick={run} disabled={loading}>
            {loading ? 'Thinking…' : 'Run'}
          </button>
        </div>
        <div className="chips">{EXAMPLES.map(([l, ex]) => (
          <button key={l} className="chip" onClick={() => setQ(ex)}>{l}</button>
        ))}</div>
      </div>
      {res && (
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
    </div>
  )
}
