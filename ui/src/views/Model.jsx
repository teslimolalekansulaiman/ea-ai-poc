import { useEffect, useState, useRef } from 'react'
import { api } from '../api'

const inp = { width: '100%', padding: '7px 10px', border: '1px solid var(--border)', borderRadius: 7, background: 'var(--bg)', color: 'var(--fg)', fontSize: 13, fontFamily: 'inherit' }
const DOMAINS = ['Motivation', 'Business', 'Data', 'Application', 'Technology', 'Realization', 'Other']

export default function Model() {
  const [m, setM] = useState(null)
  const [editing, setEditing] = useState(null)   // {kind, key, obj, isNew}
  const [err, setErr] = useState('')
  const [ingest, setIngest] = useState(null)
  const poll = useRef(null)

  const load = () => api.metamodel().then(setM).catch(e => setErr(String(e)))
  useEffect(() => { load(); return () => clearInterval(poll.current) }, [])

  async function save() {
    setErr('')
    try {
      const { kind, key, obj } = editing
      const body = { ...obj }
      if (kind === 'edge') {
        body.source_types = (obj.source_types_str || '').split(',').map(s => s.trim()).filter(Boolean)
        body.target_types = (obj.target_types_str || '').split(',').map(s => s.trim()).filter(Boolean)
      }
      const res = kind === 'node' ? await api.mmNode(key, body) : await api.mmEdge(key, body)
      setM(res); setEditing(null)
    } catch (e) { setErr(String(e).replace('Error: ', '')) }
  }
  async function del(kind, key) {
    if (!confirm(`Delete ${kind} "${key}"?`)) return
    setErr('')
    try { setM(kind === 'node' ? await api.mmNodeDel(key) : await api.mmEdgeDel(key)) }
    catch (e) { setErr(String(e).replace('Error: ', '')) }
  }
  async function reingest() {
    if (!confirm('Re-ingest all documents with the current schema? This re-runs the pipeline (minutes, LLM cost).')) return
    setIngest(await api.reingestRun())
    poll.current = setInterval(async () => {
      const s = await api.reingestStatus(); setIngest(s)
      if (!s.running && s.done) { clearInterval(poll.current); load() }
    }, 2000)
  }

  if (!m) return <div className="wrap"><div className="empty">{err || 'Loading…'}</div></div>

  const newNode = () => setEditing({ kind: 'node', key: '', isNew: true, obj: { name: '', domain: 'Business', archimate_type: '', definition: '' } })
  const newEdge = () => setEditing({ kind: 'edge', key: '', isNew: true, obj: { name: '', archimate_relationship: '', source_types_str: '', target_types_str: '', definition: '' } })
  const editNode = (n) => setEditing({ kind: 'node', key: n.key, obj: { ...n } })
  const editEdge = (e) => setEditing({ kind: 'edge', key: e.key, obj: { ...e, source_types_str: (e.source_types || []).join(', '), target_types_str: (e.target_types || []).join(', ') } })

  return (
    <div className="wrap">
      <div className="view-head"><div>
        <div className="eyebrow">Metamodel · {m.framework}</div>
        <h1>Entities &amp; relationships</h1>
        <p>The node and edge types the pipeline extracts. Edit, add or remove them; the shape is framework-agnostic, so this is where you'd swap frameworks later.</p>
      </div></div>

      {/* re-ingest banner */}
      {(m.reingest_needed || ingest) && (
        <div className="card" style={{ padding: 14, marginBottom: 16, borderLeft: '3px solid var(--warn)' }}>
          {ingest ? (
            <div>
              <b>{ingest.done ? (ingest.error ? 'Re-ingest failed' : 'Re-ingest complete') : 'Re-ingesting…'}</b>
              {ingest.error && <div style={{ color: 'var(--crit)' }}>{ingest.error}</div>}
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
                {ingest.steps.map(st => <span key={st.step} className={'pill ' + ({ ok: 'ok', failed: 'crit', running: 'info' }[st.state] || 'neutral')}>{st.step}{st.ms ? ` ${(st.ms / 1000) | 0}s` : ''}</span>)}
              </div>
            </div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
              <span>⚠ The schema changed — the extracted graph is stale.</span>
              <button className="btn primary" onClick={reingest}>Re-ingest documents</button>
            </div>
          )}
        </div>
      )}
      {err && <div className="card" style={{ padding: 12, color: 'var(--crit)', marginBottom: 14 }}>{err}</div>}

      {/* editor */}
      {editing && (
        <div className="card" style={{ padding: 16, marginBottom: 16, borderLeft: '3px solid var(--accent)' }}>
          <div style={{ fontWeight: 700, marginBottom: 10 }}>{editing.isNew ? 'New' : 'Edit'} {editing.kind} type</div>
          <div style={{ display: 'grid', gap: 8 }}>
            {editing.isNew && <input style={inp} placeholder="key (snake_case, e.g. business_service)" value={editing.key} onChange={e => setEditing({ ...editing, key: e.target.value })} />}
            <input style={inp} placeholder="name" value={editing.obj.name} onChange={e => setEditing({ ...editing, obj: { ...editing.obj, name: e.target.value } })} />
            {editing.kind === 'node' ? (
              <>
                <select style={inp} value={editing.obj.domain} onChange={e => setEditing({ ...editing, obj: { ...editing.obj, domain: e.target.value } })}>{DOMAINS.map(d => <option key={d}>{d}</option>)}</select>
                <input style={inp} placeholder="ArchiMate type (optional)" value={editing.obj.archimate_type || ''} onChange={e => setEditing({ ...editing, obj: { ...editing.obj, archimate_type: e.target.value } })} />
              </>
            ) : (
              <>
                <input style={inp} placeholder="source types (comma-separated node keys)" value={editing.obj.source_types_str} onChange={e => setEditing({ ...editing, obj: { ...editing.obj, source_types_str: e.target.value } })} />
                <input style={inp} placeholder="target types (comma-separated node keys)" value={editing.obj.target_types_str} onChange={e => setEditing({ ...editing, obj: { ...editing.obj, target_types_str: e.target.value } })} />
                <input style={inp} placeholder="ArchiMate relationship (optional)" value={editing.obj.archimate_relationship || ''} onChange={e => setEditing({ ...editing, obj: { ...editing.obj, archimate_relationship: e.target.value } })} />
              </>
            )}
            <textarea style={{ ...inp, minHeight: 44 }} placeholder="definition" value={editing.obj.definition || ''} onChange={e => setEditing({ ...editing, obj: { ...editing.obj, definition: e.target.value } })} />
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button className="btn primary" onClick={save}>Save</button>
            <button className="btn" onClick={() => setEditing(null)}>Cancel</button>
          </div>
        </div>
      )}

      {/* node types grouped by domain */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '4px 0 10px' }}>
        <h3 style={{ fontSize: 14 }}>Node types ({m.node_types.length})</h3>
        <button className="btn" onClick={newNode}>+ node type</button>
      </div>
      {DOMAINS.filter(d => m.node_types.some(n => (n.domain || 'Other') === d)).map(dom => (
        <div className="card" style={{ padding: 0, overflow: 'hidden', marginBottom: 10 }} key={dom}>
          <div style={{ padding: '8px 14px', borderBottom: '1px solid var(--border)', fontSize: 12, fontWeight: 700, color: 'var(--fg-faint)', textTransform: 'uppercase' }}>{dom}</div>
          <div className="tbl-scroll"><table className="data"><tbody>
            {m.node_types.filter(n => (n.domain || 'Other') === dom).map(n => (
              <tr key={n.key}>
                <td style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>{n.name}</td>
                <td className="mono" style={{ color: 'var(--fg-faint)' }}>{n.key}</td>
                <td>{n.definition}</td>
                <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                  <a href="#" onClick={e => { e.preventDefault(); editNode(n) }}>Edit</a>{' · '}
                  <a href="#" onClick={e => { e.preventDefault(); del('node', n.key) }} style={{ color: 'var(--crit)' }}>Delete</a>
                </td>
              </tr>
            ))}
          </tbody></table></div>
        </div>
      ))}

      {/* edge types */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '18px 0 10px' }}>
        <h3 style={{ fontSize: 14 }}>Edge types ({m.edge_types.length})</h3>
        <button className="btn" onClick={newEdge}>+ edge type</button>
      </div>
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div className="tbl-scroll"><table className="data"><thead><tr>
          <th>Relationship</th><th>Source → Target</th><th>ArchiMate</th><th></th>
        </tr></thead><tbody>
          {m.edge_types.map(e => (
            <tr key={e.key}>
              <td style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>{e.name} <span className="mono" style={{ color: 'var(--fg-faint)', fontSize: 11 }}>{e.key}</span></td>
              <td style={{ fontSize: 12 }}><span className="mono">{(e.source_types || []).join('|')}</span> → <span className="mono">{(e.target_types || []).join('|')}</span></td>
              <td style={{ color: 'var(--fg-muted)' }}>{e.archimate_relationship}</td>
              <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                <a href="#" onClick={ev => { ev.preventDefault(); editEdge(e) }}>Edit</a>{' · '}
                <a href="#" onClick={ev => { ev.preventDefault(); del('edge', e.key) }} style={{ color: 'var(--crit)' }}>Delete</a>
              </td>
            </tr>
          ))}
        </tbody></table></div>
      </div>
    </div>
  )
}
