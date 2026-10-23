import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api'
import UseCaseResult from '../components/UseCaseResult'

const fmtDate = (ts) => { try { return new Date(ts * 1000).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) } catch { return '' } }

export default function Run() {
  const { id } = useParams()
  const [view, setView] = useState('new')          // 'new' | 'history'
  const [list, setList] = useState([])
  const [ucId, setUcId] = useState(id || '')
  const [spec, setSpec] = useState(null)
  const [text, setText] = useState('')              // one demand per line
  const [running, setRunning] = useState(false)
  const [res, setRes] = useState(null)
  const [err, setErr] = useState('')
  // history
  const [runs, setRuns] = useState([])
  const [histUc, setHistUc] = useState('')
  const [viewing, setViewing] = useState(null)

  const nameOf = (uid) => list.find(u => u.id === uid)?.name || uid

  useEffect(() => { api.usecases().then(d => setList(d.usecases.filter(u => u.enabled !== false))) }, [])
  useEffect(() => { if (ucId) api.usecase(ucId).then(setSpec).catch(() => setSpec(null)); else setSpec(null) }, [ucId])
  const loadRuns = () => api.runsList(histUc || undefined).then(d => setRuns(d.runs)).catch(() => {})
  useEffect(() => { if (view === 'history') loadRuns() }, [view, histUc])  // eslint-disable-line

  function onFile(e) {
    const f = e.target.files?.[0]; if (!f) return
    const r = new FileReader()
    r.onload = () => {
      let t = String(r.result || '')
      if (t.includes(',')) {
        const rows = t.split(/\r?\n/).filter(Boolean).map(l => l.split(','))
        const header = rows[0].map(h => h.trim().toLowerCase())
        const field = (spec?.input?.batch_text_field || 'demand').toLowerCase()
        const col = header.indexOf(field) >= 0 ? header.indexOf(field) : 0
        t = rows.slice(header.includes(field) || header.includes('demand') ? 1 : 0)
          .map(r => (r[col] || '').trim()).filter(Boolean).join('\n')
      }
      setText(t)
    }
    r.readAsText(f)
  }

  function buildItems() {
    const field = spec?.input?.batch_text_field || 'demand'
    return text.split(/\r?\n/).map(l => l.trim()).filter(Boolean)
      .map((l, i) => ({ demand_no: `D-${i + 1}`, [field]: l }))
  }

  async function run() {
    setErr(''); setRes(null)
    const items = buildItems()
    if (!ucId) { setErr('Choose a use case first.'); return }
    if (!items.length) { setErr('Add at least one line of input.'); return }
    setRunning(true)
    try { setRes(await api.runUsecase(ucId, { items, k: 6 })); loadRuns() }
    catch (e) { setErr(String(e).replace('Error: ', '')) }
    setRunning(false)
  }

  async function openRun(rid) {
    setViewing(null)
    try { setViewing(await api.runGet(rid)) } catch { /* ignore */ }
  }

  const items = buildItems()

  return (
    <div className="wrap">
      <div className="view-head"><div>
        <div className="eyebrow">Run a use case</div>
        <h1>{view === 'history' ? 'Run history' : (spec ? spec.name : 'Run')}</h1>
        <p>{view === 'history'
          ? 'Every use-case run is recorded here. Open one to see its assessment exactly as it was produced.'
          : (spec ? spec.description : 'Enter or upload a list, pick a use case, and run it. Answers are grounded; anything missing is listed as what to provide.')}</p>
      </div></div>

      <div className="modes">
        <button aria-pressed={view === 'new'} onClick={() => setView('new')}>New run</button>
        <button aria-pressed={view === 'history'} onClick={() => { setView('history'); setViewing(null) }}>History</button>
      </div>

      {view === 'new' ? (
        <>
          {/* Step 1 — input */}
          <div className="card" style={{ padding: 16, marginBottom: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 700, textTransform: 'uppercase', color: 'var(--fg-faint)', marginBottom: 8 }}>1 · Input — one item per line</div>
            <textarea className="ta" value={text} onChange={e => setText(e.target.value)}
              placeholder={'e.g.\nLet citizens renew business licences online with SMS confirmation\nRetire the legacy billing system'} />
            <div className="composer-row">
              <label className="attach">Upload CSV / text<input type="file" accept=".csv,.txt" hidden onChange={onFile} /></label>
              <span className="route push">{items.length} item(s)</span>
            </div>
          </div>

          {/* Step 2 — choose use case */}
          <div className="card" style={{ padding: 16, marginBottom: 14, borderLeft: '3px solid ' + (ucId ? 'var(--ok)' : 'var(--accent)') }}>
            <div style={{ fontSize: 12, fontWeight: 700, textTransform: 'uppercase', color: 'var(--fg-faint)', marginBottom: 8 }}>2 · Choose a use case{!ucId && items.length > 0 ? ' — pick one to run →' : ''}</div>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <select value={ucId} onChange={e => setUcId(e.target.value)} style={{ minWidth: 260 }}>
                <option value="">— select a use case —</option>
                {list.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}
              </select>
              {spec?.validation?.enabled && <span className="pill info">validation gate</span>}
              {spec && <span className="pill neutral">{spec.stages.length} stage(s)</span>}
              <button className="btn primary push" onClick={run} disabled={running}>{running ? 'Running…' : 'Run'}</button>
            </div>
          </div>

          {err && <div className="card" style={{ padding: 12, color: 'var(--crit)', marginBottom: 14 }}>{err}</div>}
          {res && <UseCaseResult res={res} />}
        </>
      ) : viewing ? (
        <>
          <button className="btn" onClick={() => setViewing(null)} style={{ marginBottom: 12 }}>← Back to history</button>
          <div className="card" style={{ padding: '12px 16px', marginBottom: 14, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="pill info">{nameOf(viewing.use_case_id)}</span>
            <span className="meta">{fmtDate(viewing.created_at)}</span>
            <span className="route push">{Array.isArray(viewing.input) ? viewing.input.length : 1} item(s)</span>
          </div>
          <UseCaseResult res={viewing.result} />
        </>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
            <select value={histUc} onChange={e => setHistUc(e.target.value)} style={{ minWidth: 220 }}>
              <option value="">All use cases</option>
              {list.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}
            </select>
            <span className="route push">{runs.length} run(s)</span>
          </div>
          {runs.length === 0 ? (
            <div className="card" style={{ padding: 20, color: 'var(--fg-faint)', textAlign: 'center' }}>No runs yet — submit one from “New run”.</div>
          ) : (
            <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
              <div className="tbl-scroll"><table className="data">
                <thead><tr><th>When</th><th>Use case</th><th>Items</th><th>Status</th></tr></thead>
                <tbody>{runs.map(r => (
                  <tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => openRun(r.id)}>
                    <td style={{ whiteSpace: 'nowrap' }}>{fmtDate(r.created_at)}</td>
                    <td>{nameOf(r.use_case_id)}</td>
                    <td>{r.n_items}</td>
                    <td><span className={'pill ' + (r.status === 'done' ? 'ok' : 'neutral')}>{r.status}</span></td>
                  </tr>
                ))}</tbody>
              </table></div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
