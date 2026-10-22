import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api'
import { useCite } from '../cite'

const STATUS_PILL = { answered: 'ok', needs_source: 'warn', needs_input: 'info' }

export default function Run() {
  const { id } = useParams()
  const { open } = useCite()
  const [list, setList] = useState([])
  const [ucId, setUcId] = useState(id || '')
  const [spec, setSpec] = useState(null)
  const [text, setText] = useState('')          // one demand per line
  const [running, setRunning] = useState(false)
  const [res, setRes] = useState(null)
  const [err, setErr] = useState('')
  const [showTrace, setShowTrace] = useState(false)

  useEffect(() => { api.usecases().then(d => setList(d.usecases.filter(u => u.enabled !== false))) }, [])
  useEffect(() => { if (ucId) api.usecase(ucId).then(setSpec).catch(() => setSpec(null)); else setSpec(null) }, [ucId])

  function onFile(e) {
    const f = e.target.files?.[0]; if (!f) return
    const r = new FileReader()
    r.onload = () => {
      let t = String(r.result || '')
      // basic CSV → pull the batch column (or first col); else keep lines
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
    try { setRes(await api.runUsecase(ucId, { items, k: 6 })) }
    catch (e) { setErr(String(e).replace('Error: ', '')) }
    setRunning(false)
  }

  const items = buildItems()

  return (
    <div className="wrap">
      <div className="view-head"><div>
        <div className="eyebrow">Run a use case</div>
        <h1>{spec ? spec.name : 'Run'}</h1>
        <p>{spec ? spec.description : 'Enter or upload a list, pick a use case, and run it. Answers are grounded; anything missing is listed as what to provide.'}</p>
      </div></div>

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

      {/* Step 2 — choose use case (highlighted when not chosen) */}
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

      {/* Results */}
      {res && <Results res={res} spec={spec} open={open} showTrace={showTrace} setShowTrace={setShowTrace} />}
    </div>
  )
}

function Cell({ cell, open }) {
  if (!cell) return <td style={{ color: 'var(--fg-faint)' }}>—</td>
  const pill = STATUS_PILL[cell.status] || 'neutral'
  const val = Array.isArray(cell.value) ? cell.value.join(', ') : (cell.value ?? '')
  return (
    <td>
      {cell.status === 'answered'
        ? <span>{String(val)}</span>
        : <span className={'pill ' + pill}>{cell.status === 'needs_input' ? 'needs input' : 'needs source'}</span>}
      {cell.status !== 'answered' && cell.needs && <div className="meta" style={{ color: 'var(--fg-faint)' }}>{cell.needs}</div>}
      {(cell.evidence || []).map(e => <span key={e} className="cite" style={{ marginLeft: 4 }} onClick={() => open(e)}>{e}</span>)}
    </td>
  )
}

function Results({ res, spec, open, showTrace, setShowTrace }) {
  const stages = res.stages || []
  const rowIds = Object.keys(res.rows || {})
  const cellOf = (iid, stageId, colName) =>
    (res.rows[iid]?.[stageId]?.cells || []).find(c => c.column === colName)

  return (
    <>
      {res.rejected?.length > 0 && (
        <div className="card" style={{ padding: 16, marginBottom: 14, borderLeft: '3px solid var(--warn)' }}>
          <h3 style={{ fontSize: 13, marginBottom: 8 }}>Not assessed ({res.rejected.length})</h3>
          {res.rejected.map((r, i) => <div key={i} className="rel"><span className="t">{r.id}</span><span className="r">{r.stage}: {r.reason}</span></div>)}
        </div>
      )}

      {stages.map(st => (
        <div className="card" style={{ padding: 0, overflow: 'hidden', marginBottom: 14 }} key={st.id}>
          <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', fontWeight: 600 }}>{st.name}</div>
          <div className="tbl-scroll"><table className="data"><thead><tr>
            <th>Item</th>{st.columns.map(c => <th key={c}>{c}</th>)}
          </tr></thead><tbody>
            {rowIds.map(iid => (
              <tr key={iid}><td className="mono">{iid}</td>
                {st.columns.map(c => <Cell key={c} cell={cellOf(iid, st.id, c)} open={open} />)}
              </tr>
            ))}
          </tbody></table></div>
        </div>
      ))}

      {res.provide?.length > 0 && (
        <div className="card" style={{ padding: 16, marginBottom: 14, borderLeft: '3px solid var(--accent)' }}>
          <h3 style={{ fontSize: 13, marginBottom: 8 }}>To complete the assessment, provide:</h3>
          {res.provide.map((p, i) => <div key={i} className="rel"><span className="r">{p.status === 'needs_input' ? 'from requester' : 'ingest / source'}</span><span className="t">{p.needs}</span></div>)}
        </div>
      )}

      {res.trace?.length > 0 && (
        <div className="card" style={{ padding: 16 }}>
          <a href="#" onClick={e => { e.preventDefault(); setShowTrace(!showTrace) }}>{showTrace ? '▾' : '▸'} Run details ({res.trace.length} steps)</a>
          {showTrace && <div style={{ marginTop: 10 }}>
            {res.trace.map((t, i) => (
              <div key={i} className="rel"><span className="r mono">{t.node} · {t.ms}ms</span><span>{t.note}</span></div>
            ))}
          </div>}
        </div>
      )}
    </>
  )
}
