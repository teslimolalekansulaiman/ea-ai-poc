import { useState } from 'react'
import { useCite } from '../cite'

const STATUS_PILL = { answered: 'ok', needs_source: 'warn', needs_input: 'info' }

function Cell({ cell, open }) {
  if (!cell) return <td style={{ color: 'var(--fg-faint)' }}>—</td>
  const val = Array.isArray(cell.value) ? cell.value.join(', ') : (cell.value ?? '')
  return (
    <td>
      {cell.status === 'answered'
        ? <span>{String(val)}</span>
        : <span className={'pill ' + (STATUS_PILL[cell.status] || 'neutral')}>{cell.status === 'needs_input' ? 'needs input' : 'needs source'}</span>}
      {cell.status !== 'answered' && cell.needs && <div className="meta" style={{ color: 'var(--fg-faint)' }}>{cell.needs}</div>}
      {(cell.evidence || []).map(e => <span key={e} className="cite" style={{ marginLeft: 4 }} onClick={() => open(e)}>{e}</span>)}
    </td>
  )
}

// Renders a use-case run result: staged tables + rejected + provide list + run trace.
export default function UseCaseResult({ res }) {
  const { open } = useCite()
  const [showTrace, setShowTrace] = useState(false)
  if (!res) return null
  const stages = res.stages || []
  const rowIds = Object.keys(res.rows || {})
  const cellOf = (iid, sid, col) => (res.rows[iid]?.[sid]?.cells || []).find(c => c.column === col)

  return (
    <div style={{ marginTop: 16 }}>
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
            {res.trace.map((t, i) => <div key={i} className="rel"><span className="r mono">{t.node} · {t.ms}ms</span><span>{t.note}</span></div>)}
          </div>}
        </div>
      )}
    </div>
  )
}
