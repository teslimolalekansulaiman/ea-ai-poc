import { useEffect, useState } from 'react'
import { useCite } from '../cite'

// ---- chips: how a cell reads ---------------------------------------------------------
const CHIP = {
  answered: ['ok', 'answered'], none: ['', 'none found'], na: ['soft', 'not assessed'], confirm: ['warn', 'to confirm'],
  user: ['user', 'from you'], needs_input: ['warn', 'needs input'], needs_source: ['warn', 'needs source'],
  ret_in: ['info', 'return for information'], ret_no: ['crit', 'not a demand'], blank: ['soft', 'blank'],
}
export function Chip({ s }) {
  const [cls, label] = CHIP[s] || ['', s]
  return <span className={'cs-pill ' + cls}>{label}</span>
}
const QUIET = new Set(['answered', 'none', 'na', 'blank'])        // not worth a chip in a dense table
export const show = (v) => Array.isArray(v) ? v.join('; ') : (v ?? '')
export const count = (n, L) => `${n} ${n === 1 ? L.singular : L.plural}`
export const cap = (w) => w ? w[0].toUpperCase() + w.slice(1) : w
export const clock = (sec) => { const m = Math.floor(sec / 60), r = Math.floor(sec % 60); return String(m).padStart(2, '0') + ':' + String(r).padStart(2, '0') }

export function RowTag({ row }) {
  if (row.gate && row.gate !== 'Yes') {
    return row.gate.startsWith('Not yet') ? <span className="cs-pill info">Returned</span> : <span className="cs-pill crit">Not a demand</span>
  }
  if (!row.tag) return null
  return <span className={'cs-pill ' + (row.tag_status === 'confirm' ? 'warn' : row.tag === 'Fast-track' ? 'ok' : row.tag === 'Standard' ? 'user' : '')}>{row.tag}</span>
}

// ---- phase track: a finished phase, the current one, the next one ready to start, and locked ones ---
export function phaseKind(phases, i) {
  const st = phases[i].state.status || 'waiting'
  if (st !== 'waiting') return st === 'approved' ? 'done' : st === 'running' ? 'running' : st === 'error' ? 'error' : 'review'
  const prev = phases[i - 1]
  if (prev && prev.state.status === 'review') return 'ready'
  return 'locked'
}

export function PhaseTrack({ phases, viewed, onPick }) {
  return (
    <div className="cs-phases" role="tablist" aria-label="Phases">
      {phases.map((p, i) => {
        const kind = phaseKind(phases, i)
        const tip = kind === 'locked' ? 'Finish and approve the previous phase first' : kind === 'ready' ? 'Approve the previous phase and start this one' : ''
        return (
          <button key={p.id} role="tab" aria-selected={viewed === p.id} title={p.name + (tip ? ' — ' + tip : '')}
            className={'cs-phase ' + (viewed === p.id ? 'cur ' : '') + (kind === 'done' ? 'done ' : '') + kind}
            onClick={() => onPick(p, kind, i)}>
            <span className="n">{kind === 'done' ? '✓' : i + 1}</span><span className="pn">{p.name}</span>
            {kind === 'ready' && <span className="go">Start</span>}
          </button>
        )
      })}
    </div>
  )
}

// ---- live card: pinned while a phase runs ------------------------------------------------------
export function stepStates(phase) {
  const total = phase.state.total || 0
  let found = false
  return (phase.steps || []).map(st => {
    const n = Math.min(...st.columns.map(c => phase.progress[c] || 0))
    const done = total > 0 && n >= total
    const run = !done && !found
    if (run) found = true
    return { ...st, n, state: done ? 'done' : run ? 'run' : 'pend' }
  })
}

export function LiveCard({ phase, events, data, needs, stalled, onResume, onJump, onCancel, onActivity }) {
  const [more, setMore] = useState(true)
  const L = data.item_label
  const steps = stepStates(phase)
  const total = phase.state.total || data.items.length
  const cur = steps.find(s => s.state === 'run')
  const done = steps.filter(s => s.state === 'done').length
  const prep = !!phase.state.preparing
  const label = prep ? 'Preparing' : cur ? cur.label : 'Starting'
  const alongside = cur ? cur.columns.length - 1 : 0
  const sub = prep ? (phase.state.prep || 'Working out how to resolve each property') : cur ? `${cur.n} of ${count(total, L)}${alongside > 0 ? ` · ${alongside} more at the same time` : ''}` : ''
  const elapsed = phase.state.started ? Math.max(0, Date.now() / 1000 - phase.state.started) : 0
  const cells = (data.cells[phase.id]) || {}
  const feed = events.filter(e => e.kind === 'cell' && e.data.phase === phase.id && e.data.status !== 'user').slice(-3).reverse()
  return (
    <div className="cs-card cs-live cs-pin">
      <div className="lv">
        <span className="cs-spin" />
        <div style={{ flex: 1, minWidth: 0 }}><b>{label}</b><small>{sub}</small></div>
        {needs > 0 && <button className="cs-need-chip" onClick={onJump}>{needs} {needs > 1 ? 'need' : 'needs'} you</button>}
        <span className="t">{clock(elapsed)}</span>
        <button className="btn sm" onClick={onCancel}>Stop</button>
      </div>
      {stalled && <div className="cs-need" style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <span>No progress for a few minutes. The service may have restarted.</span><button className="btn sm" onClick={onResume}>Resume</button></div>}
      {steps.length > 0 && <div className="cs-seg" title={`${done} of ${steps.length} steps done`}>{steps.map((s, i) => <i key={i} className={s.state} />)}</div>}
      {feed.length > 0 && more && <ul className="cs-feed">{feed.map((e, i) => { const c = (cells[e.data.item] || {})[e.data.column]
        return <li key={i}><span className="id">{e.data.item.slice(-3)}</span><span>{e.data.column}{c && show(c.value) ? ': ' + String(show(c.value)).slice(0, 70) : ''}</span></li> })}</ul>}
      <div style={{ display: 'flex', gap: 14 }}>
        <button className="cs-link" style={{ fontSize: 12.5 }} onClick={onActivity}>See what the agents are doing</button>
        {feed.length > 0 && <button className="cs-link" style={{ fontSize: 12.5, color: 'var(--fg-muted)' }} onClick={() => setMore(m => !m)}>{more ? 'Hide recent' : 'Show recent'}</button>}
      </div>
    </div>
  )
}

export function ErrorCard({ phase, onResume }) {
  return (
    <div className="cs-msg"><div className="cs-av">AA</div>
      <div className="cs-body"><div className="cs-card cs-ask">
        <div className="eyebrow" style={{ color: 'var(--crit)' }}>The run stopped</div>
        <h4>{phase.name} did not finish</h4>
        <div className="cs-muted" style={{ fontSize: 13, overflowWrap: 'anywhere' }}>{phase.state.error || 'Something went wrong while running it.'}</div>
        <div className="cs-actions" style={{ marginTop: 8 }}>
          <button className="btn primary sm" onClick={onResume}>Resume</button>
          <span className="cs-cap">Everything already decided, and your answers, are kept.</span>
        </div>
      </div></div>
    </div>
  )
}

export function FinCard({ phase, n, L, onActivity }) {
  const secs = phase.state.finished && phase.state.started ? phase.state.finished - phase.state.started : null
  return (
    <div className="cs-card cs-fin">
      <span className="cs-ok">✓</span><b>{phase.name} done for {count(n, L)}</b>
      {secs !== null && <span className="cs-faint" style={{ fontSize: 12.5 }}>in {clock(secs)}</span>}
      <button className="cs-link" style={{ marginLeft: 'auto' }} onClick={onActivity}>View activity</button>
    </div>
  )
}

// ---- a question to the architect: specific, with suggestions, a type box, and a pointer ------------
export function AskCard({ q, title, docs, onAnswer }) {
  const cite = useCite()
  const [text, setText] = useState('')
  const [look, setLook] = useState(false)
  const [doc, setDoc] = useState('')
  const [where, setWhere] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { setBusy(false) }, [q.text, q.meta?.looked])          // a retry came back: the card is live again
  const send = async (body) => { setBusy(true); try { await onAnswer(body) } catch { setBusy(false) } }
  const opts = q.options || []
  const cands = q.meta?.suggestions || []
  const why = q.meta?.needs && q.meta.needs !== q.text ? q.meta.needs : ''
  return (
    <div className="cs-msg"><div className="cs-av">AA</div>
      <div className="cs-body"><div className="cs-card cs-ask">
        <div className="eyebrow" style={{ color: 'var(--warn)' }}>{q.column} needs one answer</div>
        <h4>{q.item_id}{title ? ' · ' + title : ''}: {q.text}</h4>
        {why && <div className="cs-muted" style={{ fontSize: 13 }}>{why}</div>}
        {q.meta?.looked && <div className="cs-cap">I looked in: {q.meta.looked}</div>}
        {(opts.length > 0 || cands.length > 0) && (
          <div className="cs-sugg"><div className="lbl">Suggested{opts.length ? ' · the pick list for this property' : ' from the sources'}</div>
            {opts.length > 0 && <div className="row">{opts.map(o => <button key={o} className="opt1" disabled={busy} onClick={() => send({ answer: o })}>{o}</button>)}</div>}
            {cands.map((c, i) => (
              <div className="cand" key={i}>
                <button className="pick" disabled={busy} onClick={() => send({ answer: Array.isArray(c.value) ? c.value.join('; ') : String(c.value), via: 'suggestion' })}>
                  <b>{c.label}</b>{c.why && <small>{c.why}</small>}</button>
                <span className="srcs">{c.evidence.filter(e => !e.startsWith('demand:')).map(e => <button key={e} className="cs-cite" onClick={() => cite.open(e)}>{e}</button>)}</span>
              </div>))}
          </div>)}
        <div className="cs-typebox">
          <input value={text} disabled={busy} aria-label="Type the answer" onChange={e => setText(e.target.value)}
            placeholder={opts.length ? 'Or type the answer' : 'Type the answer. It is recorded as from you, not as a sourced fact.'}
            onKeyDown={e => { if (e.key === 'Enter' && text.trim()) send({ answer: text.trim() }) }} />
          <button className="btn primary sm" disabled={busy || !text.trim()} onClick={() => send({ answer: text.trim() })}>Use this answer</button>
        </div>
        <div className="cs-actions" style={{ marginTop: 8, alignItems: 'center' }}>
          <button className="cs-link" aria-expanded={look} onClick={() => setLook(l => !l)}>Look in a document…</button>
          <span style={{ flex: 1 }} />
          <button className="btn sm" disabled={busy} onClick={() => send({ answer: null })}>I don't know, leave it open</button>
        </div>
        {look && (
          <div className="cs-lookbox">
            <select value={doc} onChange={e => setDoc(e.target.value)} aria-label="Document to look in">
              <option value="">Any ingested document</option>
              {(docs || []).map(d => <option key={d} value={d}>{d}</option>)}
            </select>
            <input value={where} onChange={e => setWhere(e.target.value)} aria-label="Where in the document"
              placeholder="Where in it (optional), for example: the HR row" />
            <div className="cs-actions" style={{ alignItems: 'center' }}>
              <button className="btn primary sm" disabled={busy || (!doc && !where.trim())}
                onClick={() => send({ mode: 'look', document: doc || null, where: where.trim() })}>{busy ? 'Looking…' : 'Look here'}</button>
              <span className="cs-cap">The document must be ingested. If it is not, add it under Sources first.</span>
            </div>
          </div>)}
      </div></div>
    </div>
  )
}

// a question already dealt with stays in the thread, with what was done
export function AnsweredCard({ q, title }) {
  const a = q.answer || ''
  const said = q.status === 'skipped' ? "You didn't know. It stays open for a later review."
    : a.startsWith('look: ') ? `You pointed to ${a.slice(6)}. Answered from what was found there, not from you.`
    : a.startsWith('suggestion: ') ? `You picked a suggestion: ${a.slice(12)}. Recorded as from you, not as a sourced fact.`
    : `You answered: ${a}. Recorded as from you.`
  return (
    <div className="cs-msg"><div className="cs-av">AA</div>
      <div className="cs-body"><div className="cs-card cs-ask done">
        <div className="eyebrow">{q.column}</div>
        <h4>{q.item_id}{title ? ' · ' + title : ''}: {q.text}</h4>
        <div className="cs-muted" style={{ fontSize: 13 }}>{said}</div>
      </div></div>
    </div>
  )
}

// ---- the result box ---------------------------------------------------------------------
export function ResultCard({ phase, next, L, onApprove, onOpenTable, onExport, onPickItem, busy }) {
  const sm = phase.summary
  const [allDec, setAllDec] = useState(false)
  const decisions = allDec ? sm.decisions : sm.decisions.slice(0, 3)
  return (
    <div className="cs-msg"><div className="cs-av">AA</div>
      <div className="cs-body"><div className="cs-card">
        <div className="eyebrow">Result · {phase.name}</div>
        <h3>{sm.assessed} of {count(sm.total, L)} assessed</h3>
        {sm.returned.length > 0 && <p className="cs-muted" style={{ margin: '-2px 0 10px' }}>
          {sm.returned.length} not assessed ({sm.returned.map(r => r.id.slice(-3)).join(', ')}). Each shows its reason in the table.</p>}
        {sm.kpis.length > 0 && <div className="cs-kpis">{sm.kpis.map(k => <div key={k.label}><span>{k.label}</span><b>{k.value}</b></div>)}</div>}
        {sm.open_questions > 0 && <p className="cs-muted" style={{ margin: '0 0 8px' }}>{sm.open_questions} question{sm.open_questions === 1 ? '' : 's'} still open above.</p>}
        {sm.decisions.length > 0 && (<>
          <div className="eyebrow">Needs a decision · {sm.decisions.length}</div>
          <div className="cs-list">{decisions.map((d, i) => (
            <button key={i} onClick={() => onPickItem(d.item)}><span className="id">{d.item.slice(-3)}</span><span>{d.text}</span></button>))}
            {sm.decisions.length > 3 && !allDec && <button className="cs-link" style={{ textAlign: 'left' }} onClick={() => setAllDec(true)}>Show {sm.decisions.length - 3} more</button>}
          </div></>)}
        <div className="cs-actions">
          {phase.state.status === 'review' && <button className="btn primary sm" disabled={busy} onClick={onApprove}>{next ? `Approve and continue to ${next.name}` : 'Approve'}</button>}
          {phase.state.status === 'approved' && <span className="cs-pill ok">Approved</span>}
          <button className="btn sm" onClick={onOpenTable}>Open full table</button>
          <button className="btn sm" onClick={onExport}>Export to Excel</button>
        </div>
        {phase.state.status === 'review' && next && <div className="cs-used" style={{ marginTop: 8 }}>Only approved, assessed {L.plural} move on. Returned {L.plural} stay out.</div>}
      </div></div>
    </div>
  )
}

// ---- cell detail: how it was resolved ---------------------------------------------------
export function CellDetail({ col, cell }) {
  const cite = useCite()
  if (!cell) return null
  const blocks = (cell.evidence || []).filter(e => !e.startsWith('demand:'))
  const fields = (cell.evidence || []).filter(e => e.startsWith('demand:')).map(e => e.slice(7))
  return (
    <div className="cs-detail">
      {cell.need && <div className="cs-need"><h5>{cell.display === 'needs_source' ? 'What the knowledge base is missing' : 'What is needed'}</h5>{cell.need}</div>}
      <div><h5>How it was resolved</h5><ol>{(cell.how || []).map((h, i) => <li key={i}>{h}</li>)}</ol></div>
      {(blocks.length > 0 || fields.length > 0) && <div><h5>Sources</h5>
        {blocks.map(b => <button key={b} className="cs-cite" onClick={() => cite.open(b)}>{b}</button>)}
        {fields.length > 0 && <div className="cs-muted">From the demand: {fields.join(', ')}</div>}</div>}
      <div className="cs-faint" style={{ fontSize: 12 }}>
        {cell.source === 'user' ? 'Supplied by you' : cell.source === 'rule' ? 'Set by a rule' : 'Decided by the model, checked in code'}
        {col?.evidence_required === false ? ' · a cited source is not required' : ''}
      </div>
    </div>
  )
}

// ---- workspace --------------------------------------------------------------------------
const stateLabel = (s) => s === 'error' ? ['crit', 'stopped'] : s === 'running' ? ['user', 'working'] : (s === 'review' || s === 'approved') ? ['ok', 'finished'] : ['', 'waiting']

export function Workspace({ data, phase, docs, L, tab, setTab, openItem, setOpenItem, openCol, setOpenCol, readiness, onReadiness, onTable, onClose }) {
  const items = data.items
  const cells = (data.cells[phase.id]) || {}
  const rows = Object.fromEntries(phase.summary.rows.map(r => [r.id, r]))
  const flagged = new Set(phase.summary.decisions.map(d => d.item))
  const detail = openItem && items.find(i => i._id === openItem)
  const title = (it) => (rows[it._id] || {}).title || it._id
  const [cls, label] = stateLabel(phase.state.status)
  const used = (d) => Object.values(data.cells).reduce((a, byItem) => a + Object.values(byItem).reduce((b, byCol) =>
    b + Object.values(byCol).filter(c => (c.evidence || []).some(e => e.startsWith(d + ':'))).length, 0), 0)
  return (
    <>
      <div className="cs-whead"><b>Workspace</b>
        <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span className={'cs-pill ' + cls}>{label}</span>
          <button className="btn sm" onClick={onClose} aria-label="Close workspace">✕</button>
        </span></div>
      <div className="cs-wtabs" role="tablist">
        {[['demands', cap(L.plural)], ['activity', 'Activity'], ['refs', 'Reference sets']].map(([k, l]) => (
          <button key={k} role="tab" className="cs-wtab" aria-selected={tab === k} onClick={() => { setTab(k); if (k !== 'demands') setOpenItem(null) }}>
            {l}{k === 'demands' && <span className="cs-pill" style={{ marginLeft: 6 }}>{items.length}</span>}</button>))}
        <button className="btn sm" onClick={onTable}>Full table</button>
      </div>
      <div className="cs-wbody">
        {tab === 'demands' && !detail && (<>
          <div className="eyebrow" style={{ padding: '10px 6px 0' }}>Phase {data.phases.findIndex(p => p.id === phase.id) + 1} · {phase.name}</div>
          {phase.summary.rows.length === 0 && <div className="cs-muted" style={{ padding: 12 }}>Nothing recorded for this phase yet.</div>}
          {items.filter(i => rows[i._id]).map(it => { const r = rows[it._id]; return (
            <button key={it._id} className="cs-drow" onClick={() => { setOpenItem(it._id); setOpenCol(null) }}>
              <div className="top"><b>{it._id.slice(-3)}</b><span>{title(it)}</span></div>
              <div className="bot"><RowTag row={r} />{flagged.has(it._id) && <span className="cs-pill warn">decision</span>}
                <span className="cs-faint" style={{ fontSize: 12 }}>{r.done} of {r.total} columns</span></div>
              <div className="cs-bar2"><i style={{ width: (100 * r.done / r.total) + '%' }} /></div>
            </button>) })}
        </>)}
        {tab === 'demands' && detail && (<>
          <button className="cs-back" onClick={() => setOpenItem(null)}>← All {L.plural}</button>
          <div style={{ padding: '2px 6px 6px' }}><div className="eyebrow mono">{detail._id}</div>
            <h3 style={{ fontSize: 15, margin: '2px 0 6px' }}>{title(detail)}</h3>{rows[detail._id] && <RowTag row={rows[detail._id]} />}</div>
          {phase.columns.map(c => { const cell = (cells[detail._id] || {})[c.name]; const open = openCol === c.name
            return (
              <div className="cs-fld" key={c.name}>
                {cell ? (
                  <button className="cs-frow" aria-expanded={open} onClick={() => setOpenCol(open ? null : c.name)}>
                    <span className="l">{c.name}</span><span className="v">{show(cell.value) || '–'}</span><span className="c"><Chip s={cell.display} /></span>
                  </button>) : (
                  <div className="cs-frow" style={{ cursor: 'default' }}><span className="l">{c.name}</span><span className="cs-skel" /><span className="c cs-faint" style={{ fontSize: 12 }}>waiting</span></div>)}
                {open && cell && <CellDetail col={c} cell={cell} />}
              </div>) })}
        </>)}
        {tab === 'activity' && (<>
          <div className="eyebrow" style={{ padding: '10px 6px 4px' }}>Steps · {phase.name}</div>
          {(phase.steps || []).length > 0 && stepStates(phase).map((s, i) => (
            <div className="cs-prop" key={i}>
              <span className={'cs-stico ' + s.state}>{s.state === 'done' ? '✓' : ''}</span>
              <span className="nm">{s.label}</span>
              <span className="ct">{s.state === 'run' ? `${s.n} of ${phase.state.total || data.items.length}` : ''}</span>
              <span className={'cs-pill ' + (s.state === 'done' ? 'ok' : s.state === 'run' ? 'user' : '')}>{s.state === 'done' ? 'done' : s.state === 'run' ? 'working' : 'waiting'}</span>
            </div>))}
          <div className="eyebrow" style={{ padding: '14px 6px 4px' }}>Properties</div>
          {phase.columns.map(c => { const n = phase.progress[c.name] || 0; const total = Math.max(1, phase.state.total || phase.summary.total)
            return <div className="cs-prop" key={c.name}><span className="nm">{c.name}</span><span className="ct">{n} of {total}</span>
              <span className={'cs-pill ' + (n >= total ? 'ok' : n ? 'user' : '')}>{n >= total ? 'done' : n ? 'working' : 'waiting'}</span></div> })}
        </>)}
        {tab === 'refs' && (<>
          <div className="eyebrow" style={{ padding: '10px 6px 4px' }}>Are the documents ready for this use case?</div>
          <div style={{ padding: '0 6px 8px' }}>
            <p className="cs-muted" style={{ margin: '0 0 8px', fontSize: 13 }}>Checks every property against what is ingested, using this case's first demands. Nothing is answered.</p>
            <button className="btn sm" onClick={onReadiness} disabled={readiness === 'loading'}>{readiness === 'loading' ? 'Checking…' : 'Check readiness'}</button>
          </div>
          {readiness && readiness !== 'loading' && readiness.error && <div className="cs-need" style={{ margin: 6 }}>{readiness.error}</div>}
          {readiness && readiness.phases && readiness.phases.map(ph => (
            <div key={ph.phase}><div className="eyebrow" style={{ padding: '8px 6px 2px' }}>{ph.name}</div>
              {ph.properties.map(p => (
                <div className="cs-prop" key={p.property} title={p.reasons.join('; ')}>
                  <span className="nm">{p.property}<div className="cs-faint" style={{ fontSize: 11.5 }}>{p.reasons.join('; ') || ('sources: ' + p.sources.join(', '))}</div></span>
                  <span className={'cs-pill ' + (p.verdict === 'ready' ? 'ok' : p.verdict === 'partial' ? 'warn' : 'crit')}>{p.verdict.replace('_', ' ')}</span>
                </div>))}</div>))}
          <div className="eyebrow" style={{ padding: '14px 6px 4px' }}>Ingested documents · {docs.length}</div>
          {docs.map(d => { const n = used(d); return (
            <div className="cs-srcitem" key={d}><b>{d}</b><p>Cited in {n} cell{n === 1 ? '' : 's'} of this case so far.</p></div>) })}
          {docs.length === 0 && <div className="cs-muted" style={{ padding: 12 }}>No documents are ingested. Add them under Sources.</div>}
        </>)}
      </div>
    </>
  )
}

// ---- the full table -----------------------------------------------------------------------
export function FullTable({ data, phase, L, onPhase, onClose, onExport, initial }) {
  const [sel, setSel] = useState(initial || null)
  const [filter, setFilter] = useState('all')
  const cells = data.cells[phase.id] || {}
  const flagged = new Set(phase.summary.decisions.map(d => d.item))
  const all = phase.summary.rows
  const rows = all.filter(r => filter === 'all' || (filter === 'attn' && flagged.has(r.id)) || (filter === 'ret' && r.gate !== 'Yes'))
  const wide = (n) => n === 'Screening observation' || n === 'Justification'
  const selCell = sel && (cells[sel.item] || {})[sel.col]
  const selCol = sel && phase.columns.find(c => c.name === sel.col)
  const started = data.phases.filter(p => p.state.status && p.state.status !== 'waiting')
  return (
    <div className="cs-sheet" role="dialog" aria-label="Table">
      <div className="cs-sheet-bar">
        <h3>{data.case.name}<div className="cs-muted" style={{ fontSize: 12, fontWeight: 400 }}>One row per {L.singular}. Click a cell to see how it was resolved.</div></h3>
        <span className="cs-tools">
          {started.length > 1 && started.map(p => <button key={p.id} className="cs-fchip" aria-pressed={p.id === phase.id} onClick={() => { setSel(null); setFilter('all'); onPhase(p.id) }}>{p.name}</button>)}
          <button className="cs-fchip" aria-pressed={filter === 'all'} onClick={() => setFilter('all')}>All</button>
          <button className="cs-fchip" aria-pressed={filter === 'attn'} onClick={() => setFilter('attn')}>Needs a decision</button>
          <button className="cs-fchip" aria-pressed={filter === 'ret'} onClick={() => setFilter('ret')}>Not assessed</button>
        </span>
        <button className="btn sm" onClick={onExport}>Export to Excel</button>
        <button className="btn sm" onClick={onClose}>Close</button>
      </div>
      <div className="cs-sheet-main">
        <div className="cs-sheet-scroll">
          <table className="cs-tbl"><thead>
            <tr className="g1"><th className="idc pre">From the input</th><th colSpan={phase.columns.length} className="out">{data.case.use_case_name} · {phase.name}</th></tr>
            <tr className="g2"><th className="idc pre">{cap(L.singular)}</th>
              {phase.columns.map(c => <th key={c.name} className={'out ' + (wide(c.name) ? 'wide' : '')}>{c.name}</th>)}</tr></thead>
            <tbody>{rows.length === 0 && <tr><td colSpan={phase.columns.length + 1} className="cs-muted" style={{ padding: 16 }}>No {L.plural} match this filter.</td></tr>}{rows.map(r => (
              <tr key={r.id} className={r.gate !== 'Yes' ? 'ret' : ''}>
                <td className="idc"><b>{r.id}</b>{r.title}</td>
                {phase.columns.map(c => { const cell = (cells[r.id] || {})[c.name]
                  if (!cell) return <td key={c.name}><span className="cs-skel" /></td>
                  const quiet = QUIET.has(cell.display)
                  return <td key={c.name} className={wide(c.name) ? 'wide' : ''}>
                    <button className="cs-cell" aria-pressed={!!sel && sel.item === r.id && sel.col === c.name} onClick={() => setSel({ item: r.id, col: c.name })}>
                      <span className="v" style={['na', 'none', 'blank'].includes(cell.display) ? { color: 'var(--fg-faint)' } : undefined}>{show(cell.value) || '–'}</span>
                      {!quiet && <Chip s={cell.display} />}
                    </button></td> })}
              </tr>))}</tbody></table>
        </div>
        {selCell && (
          <aside className="cs-drawer">
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <div><div className="eyebrow mono">{sel.item}</div><h3 style={{ fontSize: 15, marginTop: 3 }}>{sel.col}</h3></div>
              <button className="btn sm" onClick={() => setSel(null)} aria-label="Close detail">✕</button></div>
            <div><div className="eyebrow">Value</div><div style={{ fontWeight: 500, overflowWrap: 'anywhere' }}>{show(selCell.value) || '–'}</div>
              <div style={{ marginTop: 6 }}><Chip s={selCell.display} /></div></div>
            <CellDetail col={selCol} cell={selCell} />
          </aside>)}
      </div>
    </div>
  )
}
