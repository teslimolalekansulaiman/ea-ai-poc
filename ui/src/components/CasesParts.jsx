import { useState } from 'react'
import { useCite } from '../cite'

// ---- chips: how a cell reads ---------------------------------------------------------
const CHIP = {
  answered: ['ok', 'answered'], none: ['', 'none found'], na: ['soft', 'not assessed'], confirm: ['warn', 'to confirm'],
  user: ['info', 'from you'], needs_input: ['warn', 'needs input'], needs_source: ['warn', 'needs source'],
  ret_in: ['info', 'return for information'], ret_no: ['crit', 'not a demand'], blank: ['soft', 'blank'],
}
export function Chip({ s }) {
  const [cls, label] = CHIP[s] || ['', s]
  return <span className={'cs-pill ' + cls}>{label}</span>
}
const QUIET = new Set(['answered', 'none', 'na', 'blank'])        // not worth a chip in a dense table
export const show = (v) => Array.isArray(v) ? v.join('; ') : (v ?? '')

export function RowTag({ row }) {
  if (row.gate && row.gate !== 'Yes') {
    return row.gate.startsWith('Not yet') ? <span className="cs-pill info">Returned</span> : <span className="cs-pill crit">Not a demand</span>
  }
  if (!row.tag) return null
  return <span className={'cs-pill ' + (row.tag_status === 'confirm' ? 'warn' : 'ok')}>{row.tag}</span>
}

// ---- phase track ---------------------------------------------------------------------
export function PhaseTrack({ phases, viewed, onPick }) {
  return (
    <div className="cs-phases" role="tablist" aria-label="Phases">
      {phases.map((p, i) => {
        const st = p.state.status || 'waiting'
        const done = st === 'approved'
        return (
          <button key={p.id} role="tab" aria-selected={viewed === p.id} title={p.name}
            className={'cs-phase ' + (viewed === p.id ? 'cur ' : '') + (done ? 'done ' : '') + (st === 'waiting' ? 'waiting' : '')}
            onClick={() => onPick(p.id)}>
            <span className="n">{done ? '✓' : i + 1}</span><span className="pn">{p.name}</span>
          </button>
        )
      })}
    </div>
  )
}

// ---- the live card (calm: one sentence and a bar) ---------------------------------------
export function LiveCard({ phase, events, items, onCancel }) {
  const cols = phase.columns.length
  const total = items.length * cols
  const done = Object.values(phase.progress).reduce((a, b) => a + b, 0)
  const step = [...events].reverse().find(e => e.kind === 'step' && e.data.phase === phase.id)
  const label = step ? step.data.label : 'Starting'
  return (
    <div className="cs-card cs-live">
      <div className="lv">
        <span className="cs-spin" />
        <div style={{ flex: 1, minWidth: 0 }}><b>Working: {label}</b><small>{done} of {total} answers recorded</small></div>
        <button className="btn sm" onClick={onCancel}>Stop</button>
      </div>
      <div className="cs-bar2"><i style={{ width: Math.min(100, total ? (100 * done) / total : 0) + '%' }} /></div>
    </div>
  )
}

// ---- a question to the architect --------------------------------------------------------
export function AskCard({ q, title, onAnswer }) {
  return (
    <div className="cs-msg"><div className="cs-av">AA</div>
      <div className="cs-body"><div className="cs-card cs-ask">
        <div className="eyebrow" style={{ color: 'var(--warn)' }}>I need one answer</div>
        <h4>{q.item_id}{title ? ' · ' + title : ''}: {q.column}</h4>
        <div className="cs-muted" style={{ fontSize: 13 }}>{q.text}</div>
        <AskForm onAnswer={onAnswer} />
      </div></div>
    </div>
  )
}
function AskForm({ onAnswer }) {
  const [text, setText] = useState('')
  return (
    <>
      <textarea rows={2} value={text} onChange={e => setText(e.target.value)} placeholder="Type the answer. It is recorded as from you, not as a sourced fact." />
      <div className="cs-actions" style={{ marginTop: 8 }}>
        <button className="btn primary sm" disabled={!text.trim()} onClick={() => onAnswer(text.trim())}>Answer</button>
        <button className="btn sm" onClick={() => onAnswer(null)}>I don't know</button>
      </div>
    </>
  )
}

// ---- the result box ---------------------------------------------------------------------
export function ResultCard({ phase, next, onApprove, onOpenTable, onCsv, onPickItem, busy }) {
  const sm = phase.summary
  const decisions = sm.decisions
  return (
    <div className="cs-msg"><div className="cs-av">AA</div>
      <div className="cs-body"><div className="cs-card">
        <div className="eyebrow">Result · {phase.name}</div>
        <h3>{sm.assessed} of {sm.total} demand{sm.total === 1 ? '' : 's'} {sm.assessed === sm.total ? 'assessed' : 'assessed'}</h3>
        {sm.returned.length > 0 && <p className="cs-muted" style={{ margin: '-2px 0 8px' }}>
          {sm.returned.length} not assessed ({sm.returned.map(r => r.id).join(', ')}). Each shows its reason in the table.</p>}
        {sm.kpis.length > 0 && <div className="cs-kpis">{sm.kpis.map(k => <div key={k.label}><span>{k.label}</span><b>{k.value}</b></div>)}</div>}
        {sm.open_questions > 0 && <p className="cs-muted" style={{ margin: '0 0 8px' }}>{sm.open_questions} question{sm.open_questions === 1 ? '' : 's'} still open above.</p>}
        {decisions.length > 0 && (<>
          <div className="eyebrow">Needs a decision · {decisions.length}</div>
          <div className="cs-list">{decisions.map((d, i) => (
            <button key={i} onClick={() => onPickItem(d.item)}><span className="id">{d.item.slice(-3)}</span><span>{d.text}</span></button>))}</div></>)}
        <div className="cs-actions">
          {phase.state.status === 'review' && next &&
            <button className="btn primary sm" disabled={busy} onClick={onApprove}>Approve and continue to {next.name}</button>}
          {phase.state.status === 'review' && !next &&
            <button className="btn primary sm" disabled={busy} onClick={onApprove}>Approve</button>}
          {phase.state.status === 'approved' && <span className="cs-pill ok">Approved</span>}
          <button className="btn sm" onClick={onOpenTable}>Open full table</button>
          <button className="btn sm" onClick={onCsv}>Download CSV</button>
        </div>
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
export function Workspace({ data, phase, tab, setTab, openItem, setOpenItem, openCol, setOpenCol, readiness, onReadiness, onClose }) {
  const items = data.items
  const cells = (data.cells[phase.id]) || {}
  const rows = Object.fromEntries(phase.summary.rows.map(r => [r.id, r]))
  const detail = openItem && items.find(i => i._id === openItem)
  const title = (it) => (rows[it._id] || {}).title || it._id
  return (
    <>
      <div className="cs-whead"><b>Workspace</b>
        <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span className="cs-pill">{phase.state.status || 'waiting'}</span>
          <button className="btn sm cs-openwork" onClick={onClose} aria-label="Close workspace">✕</button>
        </span></div>
      <div className="cs-wtabs" role="tablist">
        {[['demands', 'Demands'], ['activity', 'Activity'], ['readiness', 'Readiness']].map(([k, l]) => (
          <button key={k} role="tab" className="cs-wtab" aria-selected={tab === k} onClick={() => { setTab(k); if (k !== 'demands') setOpenItem(null) }}>{l}</button>))}
      </div>
      <div className="cs-wbody">
        {tab === 'demands' && !detail && (<>
          <div className="eyebrow" style={{ padding: '10px 6px 0' }}>{phase.name}</div>
          {phase.summary.rows.length === 0 && <div className="cs-muted" style={{ padding: 12 }}>Nothing recorded for this phase yet.</div>}
          {items.filter(i => rows[i._id]).map(it => { const r = rows[it._id]; return (
            <button key={it._id} className="cs-drow" onClick={() => { setOpenItem(it._id); setOpenCol(null) }}>
              <div className="top"><b>{it._id.slice(-3)}</b><span>{title(it)}</span></div>
              <div className="bot"><RowTag row={r} /><span className="cs-faint" style={{ fontSize: 12 }}>{r.done} of {r.total} answers</span></div>
              <div className="cs-bar2"><i style={{ width: (100 * r.done / r.total) + '%' }} /></div>
            </button>) })}
        </>)}
        {tab === 'demands' && detail && (<>
          <button className="cs-back" onClick={() => setOpenItem(null)}>← All demands</button>
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
          <div className="eyebrow" style={{ padding: '10px 6px 4px' }}>Properties · {phase.name}</div>
          {phase.columns.map(c => { const n = phase.progress[c.name] || 0; const total = Math.max(1, phase.summary.total)
            return <div className="cs-prop" key={c.name}><span className="nm">{c.name}</span><span className="ct">{n} of {total}</span>
              <span className={'cs-pill ' + (n >= total ? 'ok' : n ? 'info' : '')}>{n >= total ? 'done' : n ? 'working' : 'waiting'}</span></div> })}
        </>)}
        {tab === 'readiness' && (<>
          <div style={{ padding: '10px 6px' }}>
            <p className="cs-muted" style={{ margin: '0 0 8px', fontSize: 13 }}>Checks every property against the documents that are ingested, using this case's first demands. Nothing is answered.</p>
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
        </>)}
      </div>
    </>
  )
}

// ---- the full table -----------------------------------------------------------------------
export function FullTable({ data, phase, onClose, onCsv, initial }) {
  const [sel, setSel] = useState(initial || null)
  const cells = data.cells[phase.id] || {}
  const rows = phase.summary.rows
  const wide = (n) => n === 'Screening observation' || n === 'Justification'
  const selCell = sel && (cells[sel.item] || {})[sel.col]
  const selCol = sel && phase.columns.find(c => c.name === sel.col)
  return (
    <div className="cs-sheet" role="dialog" aria-label="Table">
      <div className="cs-sheet-bar">
        <h3>{data.case.name}<div className="cs-muted" style={{ fontSize: 12, fontWeight: 400 }}>{phase.name}. Click a cell to see how it was resolved.</div></h3>
        <button className="btn sm" onClick={onCsv}>Download CSV</button>
        <button className="btn sm" onClick={onClose}>Close</button>
      </div>
      <div className="cs-sheet-main">
        <div className="cs-sheet-scroll">
          <table className="cs-tbl"><thead><tr><th className="idc">Demand</th>
            {phase.columns.map(c => <th key={c.name} className={wide(c.name) ? 'wide' : ''}>{c.name}</th>)}</tr></thead>
            <tbody>{rows.map(r => (
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
