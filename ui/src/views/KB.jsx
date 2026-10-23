import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { useCite } from '../cite'

export default function KB() {
  const [docs, setDocs] = useState([])
  const [q, setQ] = useState('')
  const [res, setRes] = useState(null)
  const [reing, setReing] = useState(null)      // null = idle, else the reingest status
  const [busy, setBusy] = useState(false)       // during the add/remove request itself
  const [err, setErr] = useState('')
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

  async function onRemove(docId) {
    if (!window.confirm(`Remove “${docId}” from the knowledge base?\n\nIts source document is archived and the wiki, graph and vector index are rebuilt from the remaining documents.`)) return
    setErr(''); setBusy(true)
    try { const r = await api.removeDoc(docId); setReing(r.reingest) }
    catch (e) { setErr(String(e).replace('Error: ', '')) }
    setBusy(false)
  }

  const running = !!reing?.running
  const steps = reing?.steps || []

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
          <input ref={fileRef} type="file" accept=".docx" hidden disabled={running || busy} onChange={onAdd} />
        </label>
      </div>

      {err && <div className="card" style={{ padding: 12, color: 'var(--crit)', marginBottom: 14 }}>{err}</div>}

      {reing && (
        <div className="card" style={{ padding: 14, marginBottom: 16, borderLeft: '3px solid ' + (running ? 'var(--accent)' : reing.error ? 'var(--crit)' : 'var(--ok)') }}>
          <div style={{ fontWeight: 600, marginBottom: running || steps.length ? 8 : 0 }}>
            {running ? 'Rebuilding knowledge base…' : reing.error ? 'Rebuild failed' : 'Rebuild complete'}
            {running && <span className="meta" style={{ marginLeft: 8 }}>wiki · graph · vector are being regenerated</span>}
          </div>
          {steps.length > 0 && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {steps.map(s => (
                <span key={s.step} className={'pill ' + (s.state === 'ok' ? 'ok' : s.state === 'running' ? 'info' : s.state === 'failed' ? 'crit' : 'neutral')}>
                  {s.state === 'ok' ? '✓ ' : s.state === 'running' ? '… ' : ''}{s.step}
                </span>
              ))}
            </div>
          )}
          {!running && !reing.error && <div className="meta" style={{ marginTop: 6 }}>Hard-refresh the Wiki/Map tabs to see the updated graph.</div>}
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
            <div><div className="nm">{doc.doc_id}</div><div className="meta mono">{doc.doc_id}.docx</div></div></div>
          <div><span className="pill ok">✓ Parsed</span> <span className="pill neutral">{doc.kind}</span></div>
          <div className="stats">
            <span><b>{doc.blocks}</b> blocks</span>
            <button className="btn danger sm push" disabled={running || busy} onClick={() => onRemove(doc.doc_id)}>Remove</button>
          </div>
        </div>
      ))}</div>
    </div>
  )
}
