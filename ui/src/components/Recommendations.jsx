import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
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

const NOTE = "Model's note: "

// How one answer in the draft was decided, from what the engine recorded. Read-only, and not part of the text that is approved.
function Trail({ column, trail }) {
  const cite = useCite()
  const c = trail && trail.columns[column]
  if (!trail) return <div className="rd-trail">Loading…</div>
  if (!c) return <div className="rd-trail">Nothing was recorded for this answer.</div>
  const note = c.how.find(h => h.startsWith(NOTE))
  const steps = c.how.filter(h => !h.startsWith(NOTE))
  const built = c.evidence.filter(x => x.startsWith('decided:'))
  const sources = c.evidence.filter(x => !x.startsWith('decided:'))
  return (
    <div className="rd-trail">
      {c.status !== 'answered' && <div className="rd-tr-row"><b>Not settled</b><span>{c.need || 'This answer is still open.'}</span></div>}
      {steps.length > 0 && <div className="rd-tr-row"><b>What was done</b><ul>{steps.map((h, i) => <li key={i}>{h}</li>)}</ul></div>}
      {sources.length > 0 && <div className="rd-tr-row"><b>Sources it cites</b><span className="rd-ev">{sources.map(b => <button key={b} className="cs-cite" onClick={() => cite.open(b)}>{b}</button>)}</span></div>}
      {sources.length === 0 && c.status === 'answered' && <div className="rd-tr-row"><b>Sources it cites</b><span>None. It rests on the demand itself, a definition or a rule.</span></div>}
      {built.length > 0 && <div className="rd-tr-row"><b>Built on earlier answers</b><ul>{built.map(b => <li key={b}>{b.slice('decided:'.length)}{trail.built_on[b] ? <>: <i>{trail.built_on[b]}</i></> : null}</li>)}</ul></div>}
      {note && <div className="rd-tr-row"><b>The model&apos;s note</b><span>{note.slice(NOTE.length)} <em className="rd-unchecked">The model&apos;s own words, not checked by the engine.</em></span></div>}
    </div>
  )
}

function Sheet({ caseId, phaseId, entry, onSaved, onDecided, busy, setBusy, setErr }) {
  const cite = useCite()
  const [draft, setDraft] = useState(null)        // the text being edited; null while reading
  const [asking, setAsking] = useState(false)
  const [note, setNote] = useState('')
  const [trails, setTrails] = useState({})        // how the answers were decided, by demand; loaded the first time one is opened
  const [open, setOpen] = useState('')            // the property whose trail is showing, as "demand|property"
  const e = entry
  const editing = draft !== null
  const locked = e.status === 'approved'
  const [cls, label] = STATUS[e.status] || ['', e.status]
  const doc = editing ? draft : e.doc

  useEffect(() => { setDraft(null); setAsking(false); setNote(''); setTrails({}); setOpen('') }, [e.item_id])
  const why = (column, item) => {
    if (!column) return null
    const who = item || e.item_id                                // a section of a request's draft is about one demand
    const key = who + '|' + column
    const on = open === key
    return (
      <>
        <button className="cs-link rd-why" aria-expanded={on} onClick={() => {
          setOpen(on ? '' : key)
          if (!trails[who]) api.caseDraftTrail(caseId, phaseId, who).then(t => setTrails(m => ({ ...m, [who]: t }))).catch(x => { setTrails(m => ({ ...m, [who]: { columns: {}, built_on: {} } })); setErr(String(x.message || x)) })
        }}>{on ? 'Hide how it was decided' : 'How was this decided?'}</button>
        {on && <Trail column={column} trail={trails[who]} />}
      </>)
  }

  const run = async (fn) => { setBusy(true); setErr(''); try { await fn() } catch (x) { setErr(String(x.message || x)) } finally { setBusy(false) } }
  const save = () => run(async () => { const r = await api.caseDraftSave(caseId, phaseId, e.item_id, draft); setDraft(null); onSaved(r) })
  const decide = (action, n) => run(async () => { const r = await api.caseDraftDecide(caseId, phaseId, e.item_id, action, n); setAsking(false); setNote(''); onDecided(r) })

  const set = (fn) => setDraft(d => { const n = copy(d); fn(n); return n })
  const rows = (t, min = 2) => Math.max(min, (t || '').split('\n').reduce((n, l) => n + Math.max(1, Math.ceil(l.length / 78)), 0))

  const apart = doc.sections.some(x => x.internal)             // the architect's findings are kept apart from the message that is sent
  const section = (s, i) => (!editing && !s.title && !s.body) ? null : (
    <section className="rd-sec" key={i}>
      {editing
        ? <><input className="rd-in rd-h2" aria-label="Heading" value={s.title} onChange={x => set(n => { n.sections[i].title = x.target.value })} />
            {s.internal && <span className="cs-pill">Not sent</span>}
            <textarea className="rd-in" aria-label="Text" rows={rows(s.body)} value={s.body} onChange={x => set(n => { n.sections[i].body = x.target.value })} />
            <button className="cs-link" onClick={() => set(n => { n.sections.splice(i, 1) })}>Remove this section</button></>
        : <><h3 className="rd-h">{s.title}</h3>
            {s.title === 'Evidence'
              ? <div className="rd-ev">{s.body.split('\n').filter(Boolean).map(b => <button key={b} className="cs-cite" onClick={() => cite.open(b)}>{b}</button>)}</div>
              : <Rows text={s.body} />}
            {why(s.column, s.item)}</>}
    </section>)

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
          : <>{apart && <div className="rd-eyebrow">Message to the requester</div>}
              <h3 className="rd-h">{doc.rec.title}</h3>
              <Rows text={doc.rec.body || 'No recommendation text yet.'} />
              {why(doc.rec.column)}
              {doc.facts.map((f, i) => <div className="rd-fact" key={i}><span>{f.label}:</span> <b>{f.value}</b></div>)}</>}
      </div>

      {doc.sections.map((s, i) => {
        if (!editing && s.internal) return null
        const head = s.group && !s.internal && (i === 0 || doc.sections[i - 1].group !== s.group)       // the demands handled together sit under one heading
        return <Fragment key={i}>{head && <h3 className="rd-group">{s.group}</h3>}{section(s, i)}</Fragment>
      })}
      {!editing && apart && (
        <div className="rd-arch">
          <div className="rd-eyebrow">For the architect, not sent</div>
          <div className="rd-arch-note">The findings behind the message, what is still to confirm, and the sources. They are for you to check; they are not part of what the requester receives or of the download.</div>
          {doc.sections.map((s, i) => s.internal ? section(s, i) : null)}
        </div>)}
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
          <a className="btn sm rd-dl" href={api.caseDraftExportUrl(caseId, phaseId, e.item_id)} title={apart ? 'The download holds the message only' : undefined}>{apart ? 'Download the message' : 'Download'}</a>
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
  const top = useRef(null)
  const shown = useRef(false)

  const load = useCallback(() => api.caseDrafts(caseId, phase.id).then(r => {
    setDocs(r.documents)
    setSel(s => (s && r.documents.some(d => d.item_id === s)) ? s : (r.documents[0] ? r.documents[0].item_id : null))
  }).catch(x => setErr(String(x.message || x))), [caseId, phase.id])
  useEffect(() => { load() }, [load, status, phase.state.finished])
  // The drafts are what the EA came to read, and they sit below the questions of a long thread: bring them into view once, when they first open.
  useEffect(() => {
    if (docs && docs.length && !shown.current && top.current) { shown.current = true; top.current.scrollIntoView({ block: 'start' }) }
  }, [docs])

  const replace = (r) => setDocs(ds => ds.map(d => d.item_id === r.item_id ? r : d))
  const cur = docs && docs.find(d => d.item_id === sel)
  const approved = docs ? docs.filter(d => d.status === 'approved').length : 0
  const whole = !!docs && docs.length === 1 && docs[0].item_id === '_request'          // one draft for the whole request, not one per demand

  return (
    <div className="cs-msg" ref={top}><div className="cs-av">AA</div>
      <div className="cs-body"><div className="cs-card rd">
        <div className="eyebrow">Recommendations · {phase.name}</div>
        <h3>{!docs ? 'Loading…' : whole ? (docs[0].status === 'approved' ? 'Approved' : 'One draft for the whole request') : `${approved} of ${docs.length} approved`}</h3>
        {docs && docs.length > 1 && (
          <div className="rd-list" role="tablist" aria-label="Demands">
            {docs.map(d => {
              const [cls, label] = STATUS[d.status] || ['', d.status]
              return (
                <button key={d.item_id} role="tab" aria-selected={d.item_id === sel} className={'rd-item' + (d.item_id === sel ? ' on' : '')} onClick={() => setSel(d.item_id)}>
                  <span className="id">{d.item_id.slice(-3)}</span><span className="t">{d.title}</span>{d.status !== 'draft' && <span className={'cs-pill ' + cls}>{label}</span>}
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
