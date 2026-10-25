import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { useCite } from '../cite'

const STEP_LABEL = {
  parse: 'Parsing documents', tables: 'Reading tables', subjects: 'Finding subjects',
  pages: 'Writing wiki pages', reconcile: 'Reconciling the graph',
  describe: 'Describing tables & figures', embed: 'Embedding for search', load: 'Loading the index',
  community: 'Detecting communities', summaries: 'Summarising communities',
  landscape: 'Writing landscape pages',
}
const fmtElapsed = (secs) => {
  if (!secs || secs < 0) return ''
  const m = Math.floor(secs / 60), s = Math.floor(secs % 60)
  return m ? `${m}m ${s}s` : `${s}s`
}

export default function KB() {
  const [docs, setDocs] = useState([])
  const [q, setQ] = useState('')
  const [res, setRes] = useState(null)
  const [reing, setReing] = useState(null)      // null = idle, else the reingest status
  const [busy, setBusy] = useState(false)       // during the add/remove request itself
  const [err, setErr] = useState('')
  const [pendingRemove, setPendingRemove] = useState(null)   // custom confirm dialog
  const [now, setNow] = useState(Date.now())
  const fileRef = useRef(null)
  const { open } = useCite()

  const loadDocs = () => api.docs().then(d => setDocs(d.docs)).catch(() => {})

  useEffect(() => { loadDocs() }, [])
  // On mount, pick up a rebuild that may already be running (e.g. from the Model tab).
  useEffect(() => { api.reingestStatus().then(s => { if (s.running) setReing(s) }).catch(() => {}) }, [])

  // Poll while a rebuild is running; refresh the document list when it finishes.
  useEffect(() => {
    if (!reing?.running) return
    const t = setInterval(async () => {
      try {
        const s = await api.reingestStatus()
        setReing(s)
        if (!s.running) { clearInterval(t); loadDocs(); if (s.error) setErr(s.error) }
      } catch { /* keep polling */ }
    }, 1500)
    return () => clearInterval(t)
  }, [reing?.running])

  useEffect(() => {
    const t = setTimeout(async () => {
      if (!q.trim()) { setRes(null); return }
      try { setRes(await api.kb(q, 8)) } catch { setRes({ results: [] }) }
    }, 350)
    return () => clearTimeout(t)
  }, [q])

  async function onAdd(e) {
    const f = e.target.files?.[0]; if (fileRef.current) fileRef.current.value = ''
    if (!f) return
    setErr(''); setBusy(true)
    try { const r = await api.addDoc(f); setReing(r.reingest) }
    catch (e) { setErr(String(e).replace('Error: ', '')) }
    setBusy(false)
  }

  async function doRemove(docId) {
    setPendingRemove(null); setErr(''); setBusy(true)
    try { const r = await api.removeDoc(docId); setReing(r.reingest) }
    catch (e) { setErr(String(e).replace('Error: ', '')) }
    setBusy(false)
  }

  const running = !!reing?.running
  const steps = reing?.steps || []
  const doneSteps = steps.filter(s => s.state === 'ok').length
  const pct = steps.length ? Math.round(((doneSteps + (running ? 0.4 : 0)) / steps.length) * 100) : (reing && !reing.error ? 100 : 0)
  const elapsed = reing?.started ? fmtElapsed(now / 1000 - reing.started) : ''

  // tick a clock while rebuilding, for the elapsed timer
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [running])

  return (
    <div className="wrap">
      <div className="view-head">
        <div>
          <div className="eyebrow">Knowledge base</div>
          <h1>Foundational sources</h1>
          <p>The documents every answer is grounded in. Adding or removing a document rebuilds the wiki, graph and vector index from the whole set.</p>
        </div>
        <label className={'btn primary' + (running || busy ? ' disabled' : '')}>
          {busy ? 'Uploading…' : '+ Add document'}
          <input ref={fileRef} type="file" accept=".docx,.pptx" hidden disabled={running || busy} onChange={onAdd} />
        </label>
      </div>

      {err && <div className="card" style={{ padding: 12, color: 'var(--crit)', marginBottom: 14 }}>{err}</div>}

      {reing && (
        <div className={'card reing' + (running ? ' running' : reing.error ? ' failed' : ' done')}>
          <div className="reing-head">
            <div className="reing-title">
              {running ? <span className="spin" /> : <span className="dot">{reing.error ? '!' : '✓'}</span>}
              {running ? 'Rebuilding your knowledge base' : reing.error ? 'Rebuild failed' : 'Rebuild complete'}
            </div>
            <span className="meta">{running ? `${pct}%${elapsed ? ' · ' + elapsed : ''}` : (reing.error ? '' : `done in ${elapsed || '—'}`)}</span>
          </div>
          <div className="progress"><i style={{ width: pct + '%', background: reing.error ? 'var(--crit)' : undefined }} /></div>
          {steps.length > 0 && (
            <div className="reing-steps">
              {steps.map(s => (
                <div key={s.step} className={'reing-step ' + s.state}>
                  <span className="ic">{s.state === 'ok' ? '✓' : s.state === 'running' ? <span className="spin sm" /> : s.state === 'failed' ? '✕' : '○'}</span>
                  <span className="lbl">{STEP_LABEL[s.step] || s.step}</span>
                  {s.note && <span className="meta" style={{ marginLeft: 8 }}>{s.note}</span>}
                  {s.ms != null && <span className="t">{(s.ms / 1000).toFixed(1)}s</span>}
                </div>
              ))}
            </div>
          )}
          {reing.error && <div className="meta" style={{ marginTop: 8, color: 'var(--crit)' }}>{reing.error}</div>}
          {!running && !reing.error && <div className="meta" style={{ marginTop: 8 }}>The wiki, graph and vector index are updated. Reopen the Wiki/Map tabs to see the changes.</div>}
        </div>
      )}

      <input className="search" placeholder="Search the knowledge base (semantic)…" value={q}
        onChange={(e) => setQ(e.target.value)}
        style={{ width: '100%', padding: '9px 12px', border: '1px solid var(--border)', borderRadius: 7, background: 'var(--surface)', color: 'var(--fg)', fontSize: 13, marginBottom: 14 }} />
      {res && (
        <div className="card" style={{ padding: 0, overflow: 'hidden', marginBottom: 20 }}>
          <div className="tbl-scroll"><table className="data">
            <thead><tr><th>Block</th><th>Section</th><th>Text</th></tr></thead>
            <tbody>{res.results.map((r, i) => (
              <tr key={i}>
                <td><span className="cite" onClick={() => open(r.block_id)}>{r.block_id}</span></td>
                <td style={{ whiteSpace: 'nowrap' }}>{r.section}</td>
                <td>{(r.text || '').slice(0, 110)}…</td>
              </tr>
            ))}</tbody>
          </table></div>
        </div>
      )}
      <div className="kb-grid">{docs.map((doc) => (
        <div className="card kb-doc" key={doc.doc_id}>
          <div className="top"><div className="fi" style={{ background: 'var(--l-application)' }}>DOCX</div>
            <div><div className="nm">{doc.doc_id}</div><div className="meta mono">{doc.file || doc.doc_id + '.docx'}</div></div></div>
          <div><span className="pill ok">✓ Parsed</span> <span className="pill neutral">{doc.kind}</span></div>
          <div className="stats">
            <span><b>{doc.blocks}</b> blocks</span>
            <button className="btn danger sm push" disabled={running || busy} onClick={() => setPendingRemove(doc.doc_id)}>Remove</button>
          </div>
        </div>
      ))}</div>

      {pendingRemove && (
        <div className="modal-bg open" onClick={(e) => { if (e.target === e.currentTarget) setPendingRemove(null) }}>
          <div className="modal confirm" role="dialog" aria-modal="true">
            <div className="mh"><strong>Remove document</strong><button className="x" onClick={() => setPendingRemove(null)}>×</button></div>
            <div className="mb">
              <p>Remove <b>{pendingRemove}</b> from the knowledge base?</p>
              <p className="meta">Its source file is archived (not deleted), and the wiki, graph and vector index are rebuilt from the remaining documents. This takes a few minutes.</p>
              <div className="confirm-row">
                <button className="btn" onClick={() => setPendingRemove(null)}>Cancel</button>
                <button className="btn danger" onClick={() => doRemove(pendingRemove)}>Remove &amp; rebuild</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
