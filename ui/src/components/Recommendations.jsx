import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { useCite } from '../cite'

// A phase shown as documents: one draft per demand. The architect reads it, edits any heading or
// text, and approves it or returns it with a note. The text is composed on the server from the
// phase's results; what is shown here is what is stored, so the screen and the record agree.

const STATUS = { draft: ['warn', 'Draft for review'], approved: ['ok', 'Approved'], returned: ['crit', 'Returned with a note'] }
const when = (t) => t ? new Date(t * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : ''
const copy = (o) => JSON.parse(JSON.stringify(o))

function Rows({ text }) {
  return <p className="rd-text">{text}</p>
}

function Sheet({ caseId, phaseId, entry, onSaved, onDecided, busy, setBusy, setErr }) {
  const cite = useCite()
  const [draft, setDraft] = useState(null)        // the text being edited; null while reading
  const [asking, setAsking] = useState(false)
  const [note, setNote] = useState('')
  const e = entry
  const editing = draft !== null
  const locked = e.status === 'approved'
  const [cls, label] = STATUS[e.status] || ['', e.status]
  const doc = editing ? draft : e.doc

  useEffect(() => { setDraft(null); setAsking(false); setNote('') }, [e.item_id])

  const run = async (fn) => { setBusy(true); setErr(''); try { await fn() } catch (x) { setErr(String(x.message || x)) } finally { setBusy(false) } }
  const save = () => run(async () => { const r = await api.caseDraftSave(caseId, phaseId, e.item_id, draft); setDraft(null); onSaved(r) })
  const decide = (action, n) => run(async () => { const r = await api.caseDraftDecide(caseId, phaseId, e.item_id, action, n); setAsking(false); setNote(''); onDecided(r) })

  const set = (fn) => setDraft(d => { const n = copy(d); fn(n); return n })
  const rows = (t, min = 2) => Math.max(min, (t || '').split('\n').reduce((n, l) => n + Math.max(1, Math.ceil(l.length / 78)), 0))

  return (
    <article className="rd-sheet" aria-label={'Recommendation for ' + e.item_id}>
      <div className="rd-top">
        <span className={'cs-pill ' + cls}>{label}</span>
        {e.edited && <span className="rd-note">Edited by the architect. The original draft is kept with the record.</span>}
        {e.stale && !locked && <span className="rd-note warn">The results behind this draft changed after it was saved.</span>}
        <span className="sp" />
        {!locked && !editing && <button className="btn sm" disabled={busy} onClick={() => { setDraft(copy(e.doc)); setAsking(false) }}>Edit</button>}
        {editing && <button className="btn sm" disabled={busy} onClick={() => setDraft(null)}>Cancel</button>}
        {editing && <button className="btn sm primary" disabled={busy} onClick={save}>Save text</button>}
      </div>

      {editing
        ? <><input className="rd-in rd-h1" aria-label="Title" value={doc.title} onChange={x => set(n => { n.title = x.target.value })} />
            <input className="rd-in" aria-label="Demand line" value={doc.meta} onChange={x => set(n => { n.meta = x.target.value })} /></>
        : <><h2 className="rd-title">{doc.title}</h2><div className="rd-meta">{doc.meta}</div></>}

      <div className="rd-rec">
        {editing
          ? <><input className="rd-in rd-h2" aria-label="Heading of the recommendation" value={doc.rec.title} onChange={x => set(n => { n.rec.title = x.target.value })} />
              <textarea className="rd-in rd-lead" aria-label="The recommendation" rows={rows(doc.rec.body, 3)} value={doc.rec.body} onChange={x => set(n => { n.rec.body = x.target.value })} />
              {doc.facts.map((f, i) => (
                <div className="rd-fact-edit" key={i}>
                  <input className="rd-in" aria-label="Label" value={f.label} onChange={x => set(n => { n.facts[i].label = x.target.value })} />
                  <input className="rd-in" aria-label="Value" value={f.value} onChange={x => set(n => { n.facts[i].value = x.target.value })} />
                </div>))}</>
          : <><h3 className="rd-h">{doc.rec.title}</h3>
              <Rows text={doc.rec.body || 'No recommendation text yet.'} />
              {doc.facts.map((f, i) => <div className="rd-fact" key={i}><span>{f.label}:</span> <b>{f.value}</b></div>)}</>}
      </div>

      {doc.sections.map((s, i) => (!editing && !s.title && !s.body) ? null : (
        <section className="rd-sec" key={i}>
          {editing
            ? <><input className="rd-in rd-h2" aria-label="Heading" value={s.title} onChange={x => set(n => { n.sections[i].title = x.target.value })} />
                <textarea className="rd-in" aria-label="Text" rows={rows(s.body)} value={s.body} onChange={x => set(n => { n.sections[i].body = x.target.value })} />
                <button className="cs-link" onClick={() => set(n => { n.sections.splice(i, 1) })}>Remove this section</button></>
            : <><h3 className="rd-h">{s.title}</h3>
                {s.title === 'Evidence'
                  ? <div className="rd-ev">{s.body.split('\n').filter(Boolean).map(b => <button key={b} className="cs-cite" onClick={() => cite.open(b)}>{b}</button>)}</div>
                  : <Rows text={s.body} />}</>}
        </section>))}
      {editing && <div><button className="btn sm" onClick={() => set(n => { n.sections.push({ title: 'New section', body: '' }) })}>Add a section</button></div>}

      <p className="rd-foot">Built from the answers of the phases before it and the sources listed above. Nothing in it is a decision until it is approved.</p>

      {e.status === 'approved' && <div className="rd-banner ok"><b>Approved{e.decided_at ? ' on ' + when(e.decided_at) : ''}.</b> This is the recommendation for {e.item_id}. The text is locked; running the phase again will not change it.</div>}
      {e.status === 'returned' && <div className="rd-banner crit"><b>Returned.</b> {e.note}</div>}

      {asking && !editing && (
        <div className="rd-ask">
          <label htmlFor="rd-note">What should change before this can be approved?</label>
          <textarea id="rd-note" className="rd-in" rows={3} value={note} onChange={x => setNote(x.target.value)} />
          <div className="rd-actions">
            <button className="btn sm primary" disabled={busy || !note.trim()} onClick={() => decide('return', note)}>Return it</button>
            <button className="btn sm" onClick={() => setAsking(false)}>Cancel</button>
          </div>
        </div>)}

      {!editing && !asking && (
        <div className="rd-actions">
          {e.status === 'draft' && <button className="btn primary" disabled={busy} onClick={() => decide('approve')}>Approve</button>}
          {e.status === 'draft' && <button className="btn" disabled={busy} onClick={() => setAsking(true)}>Return with a note</button>}
          {e.status === 'returned' && <button className="btn" disabled={busy} onClick={() => decide('reopen')}>Reopen as a draft</button>}
          <a className="btn sm rd-dl" href={api.caseDraftExportUrl(caseId, phaseId, e.item_id)}>Download</a>
        </div>)}
    </article>
  )
}

export function Recommendations({ caseId, phase, onOpenTable, onExport, onChanged }) {
  const [docs, setDocs] = useState(null)
  const [sel, setSel] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const status = phase.state.status

  const load = useCallback(() => api.caseDrafts(caseId, phase.id).then(r => {
    setDocs(r.documents)
    setSel(s => (s && r.documents.some(d => d.item_id === s)) ? s : (r.documents[0] ? r.documents[0].item_id : null))
  }).catch(x => setErr(String(x.message || x))), [caseId, phase.id])
  useEffect(() => { load() }, [load, status, phase.state.finished])

  const replace = (r) => setDocs(ds => ds.map(d => d.item_id === r.item_id ? r : d))
  const cur = docs && docs.find(d => d.item_id === sel)
  const approved = docs ? docs.filter(d => d.status === 'approved').length : 0

  return (
    <div className="cs-msg"><div className="cs-av">AA</div>
      <div className="cs-body"><div className="cs-card rd">
        <div className="eyebrow">Recommendations · {phase.name}</div>
        <h3>{docs ? `${approved} of ${docs.length} approved` : 'Loading…'}</h3>
        {docs && docs.length > 1 && (
          <div className="rd-list" role="tablist" aria-label="Demands">
            {docs.map(d => {
              const [cls, label] = STATUS[d.status] || ['', d.status]
              return (
                <button key={d.item_id} role="tab" aria-selected={d.item_id === sel} className={'rd-item' + (d.item_id === sel ? ' on' : '')} onClick={() => setSel(d.item_id)}>
                  <span className="id">{d.item_id.slice(-3)}</span><span className="t">{d.title}</span><span className={'cs-pill ' + cls}>{label}</span>
                </button>)
            })}
          </div>)}
        {err && <div className="cs-need">{err}</div>}
        {cur && <Sheet key={cur.item_id} caseId={caseId} phaseId={phase.id} entry={cur} busy={busy} setBusy={setBusy} setErr={setErr}
          onSaved={replace} onDecided={(r) => { replace(r); if (onChanged) onChanged() }} />}
        <div className="cs-actions">
          <button className="btn sm" onClick={onOpenTable}>Open full table</button>
          <button className="btn sm" onClick={onExport}>Export to Excel</button>
        </div>
      </div></div>
    </div>
  )
}
