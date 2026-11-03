import { useState } from 'react'

// "What I have so far", inside the chat: each demand's values, the words each was taken from, and what is still missing. It is
// read-only until the person clicks a value to correct it; a correction is theirs, and is marked as entered by them.

const tagOf = (p) => (p.by === 'file' ? `From ${p.source}` : 'From your message') + (p.chosen ? ' · chosen from your words' : '')

function Edit({ field, value, busy, onSave, onCancel }) {
  const [v, setV] = useState(value)
  const input = field.type === 'enum'
    ? <select className="rq-in" aria-label={field.label} value={v} onChange={e => setV(e.target.value)}>{field.values.map(x => <option key={x} value={x}>{x}</option>)}</select>
    : field.type === 'textarea'
      ? <textarea className="rq-in" aria-label={field.label} rows={3} value={v} onChange={e => setV(e.target.value)} />
      : <input className="rq-in" aria-label={field.label} value={v} onChange={e => setV(e.target.value)} />
  return (
    <div className="rc-edit">{input}
      <button className="btn sm primary" disabled={busy || !v.trim() || v === value} onClick={() => onSave(v)}>Save</button>
      <button className="btn sm" onClick={onCancel}>Cancel</button>
    </div>)
}

function Demand({ it, fields, busy, onSave }) {
  const [open, setOpen] = useState(null)         // the field whose quote is showing
  const [editing, setEditing] = useState(null)   // the field being corrected
  const from = it.from || {}
  const set = it.set || {}
  const given = fields.filter(f => (it.values[f.name] || '').trim())
  return (
    <div className="rc-dem">
      <div className="rc-dh"><span className="rq-id">{it.id}</span><span className="rq-title">{it.title}</span>
        {it.problems.length > 0 ? <span className="cs-pill crit">ID problem</span>
          : it.missing.length === 0 ? <span className="cs-pill ok">Complete</span>
            : <span className="cs-pill warn">Missing {it.missing.length}</span>}
      </div>
      {given.map(f => {
        const p = from[f.name]
        return (
          <div key={f.name} className="rq-frow">
            <span className="rq-fl">{f.label}</span>
            {editing === f.name
              ? <Edit field={f} value={it.values[f.name]} busy={busy} onCancel={() => setEditing(null)} onSave={async (v) => { if (await onSave(it.id, f.name, v)) setEditing(null) }} />
              : <button className="rc-val" title="Click to correct this" onClick={() => setEditing(f.name)}>{it.values[f.name]}</button>}
            {editing !== f.name && (p
              ? <button className="cs-pill info rq-tag" aria-expanded={open === f.name} onClick={() => setOpen(open === f.name ? null : f.name)}>{tagOf(p)}</button>
              : set[f.name] ? <span className="cs-pill user">You entered</span> : null)}
            {open === f.name && p && p.quote && <blockquote className="rq-quote">{p.quote}</blockquote>}
          </div>)
      })}
      {it.missing.length > 0 && (
        <div className="rq-frow"><span className="rq-fl">Missing</span>
          <span className="rq-fv">{it.missing.map(m => m.label + (it.declined.includes(m.name) ? ' (ask the requester)' : '')).join('; ')}</span></div>)}
      {it.problems.map(p => <div key={p} className="cs-need">{p}</div>)}
    </div>)
}

export function RequestSummary({ req, busy, onSave }) {
  const s = req.summary
  const L = req.item_label
  return (
    <details className="rc-sum">
      <summary>What I have so far<span className="cs-faint"> · {s.total} {s.total === 1 ? L.singular : L.plural}, {s.incomplete === 0 ? 'all complete' : `${s.incomplete} incomplete`}</span></summary>
      <div className="rc-sumbody">
        {req.unmatched.length > 0 && <div className="cs-faint" style={{ fontSize: 12.5 }}>Columns not recognised and ignored: {req.unmatched.join(', ')}.</div>}
        {req.items.map(it => <Demand key={it.id} it={it} fields={req.fields} busy={busy} onSave={onSave} />)}
      </div>
    </details>)
}
