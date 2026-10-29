import { useEffect, useMemo, useRef, useState } from 'react'
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
  const [kinds, setKinds] = useState({})        // kind -> what it means, from the server
  const [limits, setLimits] = useState({ max_file_mb: 25, max_batch_files: 20, max_batch_mb: 100 })
  const [staged, setStaged] = useState([])       // files chosen but not yet uploaded: [{id, file, kind}]
  const [marked, setMarked] = useState([])       // doc_ids marked for removal
  const [outcome, setOutcome] = useState(null)   // the verdict on every file of the last applied batch
  const [dragging, setDragging] = useState(false)
  const [now, setNow] = useState(Date.now())
  const fileRef = useRef(null)
  const { open } = useCite()

  const loadDocs = () => api.docs().then(d => { setDocs(d.docs); if (d.kinds) setKinds(d.kinds); if (d.limits) setLimits(d.limits) }).catch(() => {})

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

  const stem = (n) => n.replace(/\.[^.]+$/, '')
  const mb = (n) => n < 1048576 ? Math.max(1, Math.round(n / 1024)) + ' KB' : (n >= 10485760 ? Math.round(n / 1048576) : Math.round(n / 104858) / 10) + ' MB'

  function stage(list) {
    const files = Array.from(list || [])
    if (!files.length) return
    setOutcome(null)
    setStaged(prev => {
      const names = new Set(files.map(f => f.name))
      return [...prev.filter(e => !names.has(e.file.name)),                // choosing a name again replaces the earlier choice
        ...files.map(f => ({ id: f.name + '|' + f.size + '|' + Math.random().toString(36).slice(2, 7), file: f, kind: 'architecture' }))]
    })
  }
  function onPick(e) { stage(e.target.files); if (fileRef.current) fileRef.current.value = '' }
  function onDrop(e) { e.preventDefault(); setDragging(false); if (!running && !busy) stage(e.dataTransfer.files) }

  // The verdict on each chosen file that the screen can give before anything is sent. The server checks again (it has the last word).
  const checked = useMemo(() => {
    let count = 0, bytes = 0
    const stems = new Set()
    return staged.map(e => {
      const f = e.file, n = f.name
      let problem = '', note = ''
      const existing = docs.find(d => d.doc_id === stem(n))
      if (!/\.(docx|pptx)$/i.test(n)) problem = 'Only .docx and .pptx documents are supported.'
      else if (f.size === 0) problem = 'The file is empty.'
      else if (f.size > limits.max_file_mb * 1048576) problem = `Larger than ${limits.max_file_mb} MB.`
      else if (existing && existing.file && existing.file !== n) problem = `'${existing.file}' already uses the name '${stem(n)}'; rename it.`
      else if (stems.has(stem(n))) problem = `Another chosen file already uses the name '${stem(n)}'.`
      else if (count + 1 > limits.max_batch_files) problem = `Over the limit of ${limits.max_batch_files} files in one batch; add it in the next batch.`
      else if (bytes + f.size > limits.max_batch_mb * 1048576) problem = `Over the limit of ${limits.max_batch_mb} MB in one batch; add it in the next batch.`
      if (!problem) { count += 1; bytes += f.size; stems.add(stem(n)); if (existing) note = 'Replaces the document of the same name.' }
      return { ...e, problem, note }
    })
  }, [staged, docs, limits])
  const valid = checked.filter(e => !e.problem)
  const changes = valid.length + marked.length

  const toggleMark = (id) => setMarked(m => m.includes(id) ? m.filter(x => x !== id) : [...m, id])
  const setKind = (id, kind) => setStaged(st => st.map(e => e.id === id ? { ...e, kind } : e))
  const dropStaged = (id) => setStaged(st => st.filter(e => e.id !== id))
  function clearChanges() { setStaged([]); setMarked([]) }

  async function onApply() {
    setErr(''); setOutcome(null); setBusy(true)
    const results = []
    let next = 0
    const worker = async () => {                                          // three files at a time: each is its own request, so none hits the request size limit together
      while (next < valid.length) {
        const e = valid[next++]
        try { results.push(await api.uploadDoc(e.file, e.kind)) }
        catch (x) { results.push({ name: e.file.name, state: 'rejected', reason: String(x).replace('Error: ', '') }) }
      }
    }
    await Promise.all([worker(), worker(), worker()])
    const saved = results.filter(r => r.state === 'added' || r.state === 'replaced').length
    const gone = marked.filter(Boolean)
    try {
      if (saved || gone.length) { const r = await api.applyDocs(gone, saved); setReing(r.reingest) }
    } catch (x) {
      setErr(String(x).replace('Error: ', '') + (saved ? ' The files above were saved but nothing was rebuilt; fix this and press Rebuild.' : ''))
    }
    setOutcome([...results, ...gone.map(d => ({ name: d, state: 'removed', reason: 'Archived, not deleted.' }))].concat(
      checked.filter(e => e.problem).map(e => ({ name: e.file.name, state: 'rejected', reason: e.problem }))))
    setStaged([]); setMarked([])
    setBusy(false)
    loadDocs()
  }

  async function onRebuild() {
    setErr(''); setBusy(true)
    try { setReing(await api.reingestRun()) }
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
          <p>The documents every answer is grounded in. Choose as many files as you like and mark any to remove, then apply once: the wiki, graph and vector index are rebuilt a single time for the whole batch.</p>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button className="btn" disabled={running || busy} onClick={onRebuild}
            title="Rebuild from the current documents, with no change to them">Rebuild</button>
          <label className={'btn primary' + (running || busy ? ' disabled' : '')}>
            {busy ? 'Working…' : '+ Add documents'}
            <input ref={fileRef} type="file" accept=".docx,.pptx" multiple hidden disabled={running || busy} onChange={onPick} />
          </label>
        </div>
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

      <div className={'card dropzone' + (dragging ? ' over' : '')} onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)} onDrop={onDrop}>
        Drop .docx or .pptx files here, or use <b>+ Add documents</b>. Up to {limits.max_batch_files} files and {limits.max_batch_mb} MB in a batch, {limits.max_file_mb} MB a file.
      </div>

      {(staged.length > 0 || marked.length > 0) && (
        <div className="card changes">
          <div className="changes-head">
            <div><b>{valid.length}</b> to add{valid.length ? ` (${mb(valid.reduce((n, e) => n + e.file.size, 0))})` : ''} · <b>{marked.length}</b> to remove
              <span className="meta"> · one rebuild for all of it</span></div>
            <div className="changes-actions">
              {staged.length > 1 && (
                <label className="meta">Set every file to{' '}
                  <select value="" onChange={(e) => e.target.value && setStaged(st => st.map(x => ({ ...x, kind: e.target.value })))}>
                    <option value="">kind…</option>
                    {Object.keys(kinds).map(k => <option key={k} value={k}>{k}</option>)}
                  </select>
                </label>
              )}
              <button className="btn" disabled={busy} onClick={clearChanges}>Clear</button>
              <button className="btn primary" disabled={running || busy || !changes} onClick={onApply}
                title={running ? 'A rebuild is running; wait for it to finish' : ''}>{busy ? 'Applying…' : `Apply ${changes} change${changes === 1 ? '' : 's'}`}</button>
            </div>
          </div>
          <div className="tbl-scroll"><table className="data">
            <thead><tr><th>File</th><th>Kind</th><th>Verdict</th><th /></tr></thead>
            <tbody>
              {checked.map(e => (
                <tr key={e.id}>
                  <td>{e.file.name} <span className="meta">{mb(e.file.size)}</span></td>
                  <td>{e.problem ? <span className="meta">—</span> : (
                    <select value={e.kind} onChange={(ev) => setKind(e.id, ev.target.value)} title={kinds[e.kind] || ''}>
                      {Object.keys(kinds).map(k => <option key={k} value={k}>{k}</option>)}
                    </select>)}</td>
                  <td>{e.problem ? <span className="pill crit">not added</span> : <span className="pill ok">{e.note ? 'replace' : 'add'}</span>}{' '}
                    <span className="meta" style={e.problem ? { color: 'var(--crit)' } : undefined}>{e.problem || e.note}</span></td>
                  <td><button className="btn sm" disabled={busy} onClick={() => dropStaged(e.id)}>×</button></td>
                </tr>
              ))}
              {marked.map(id => (
                <tr key={'rm-' + id}>
                  <td>{id}</td><td><span className="meta">—</span></td>
                  <td><span className="pill warn">remove</span> <span className="meta">its file is archived, not deleted</span></td>
                  <td><button className="btn sm" disabled={busy} onClick={() => toggleMark(id)}>Undo</button></td>
                </tr>
              ))}
            </tbody>
          </table></div>
          {Object.keys(kinds).length > 0 && (
            <div className="meta" style={{ marginTop: 8 }}>{Object.entries(kinds).map(([k, v]) => <div key={k}><b>{k}</b>: {v}</div>)}</div>
          )}
        </div>
      )}

      {outcome && (
        <div className="card changes">
          <div className="changes-head"><b>What happened to each file</b><button className="btn sm" onClick={() => setOutcome(null)}>Close</button></div>
          <div className="tbl-scroll"><table className="data"><tbody>
            {outcome.map((r, i) => (
              <tr key={i}><td>{r.name}</td>
                <td><span className={'pill ' + (r.state === 'rejected' ? 'crit' : r.state === 'unchanged' ? 'neutral' : r.state === 'removed' ? 'warn' : 'ok')}>{r.state}</span></td>
                <td className="meta">{r.reason}</td></tr>
            ))}
          </tbody></table></div>
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
      {docs.length > 1 && (
        <div className="meta" style={{ marginBottom: 8 }}>
          <button className="btn sm" disabled={running || busy} onClick={() => setMarked(marked.length === docs.length ? [] : docs.map(d => d.doc_id))}>
            {marked.length === docs.length ? 'Select none' : 'Select all'}</button>{' '}
          Tick the documents to remove, then apply.
        </div>
      )}
      <div className="kb-grid">{docs.map((doc) => (
        <div className={'card kb-doc' + (marked.includes(doc.doc_id) ? ' marked' : '')} key={doc.doc_id}>
          <div className="top"><div className="fi" style={{ background: 'var(--l-application)' }}>DOCX</div>
            <div><div className="nm">{doc.doc_id}</div><div className="meta mono">{doc.file || doc.doc_id + '.docx'}</div></div></div>
          <div><span className="pill ok">✓ Parsed</span> <span className="pill neutral">{doc.kind}</span></div>
          <div className="stats">
            <span><b>{doc.blocks}</b> blocks</span>
            <label className="push meta" style={{ display: 'inline-flex', gap: 6, alignItems: 'center', cursor: 'pointer' }}>
              <input type="checkbox" checked={marked.includes(doc.doc_id)} disabled={running || busy} onChange={() => toggleMark(doc.doc_id)} /> Remove
            </label>
          </div>
        </div>
      ))}</div>

    </div>
  )
}
