import { useState } from 'react'
import { api } from '../api'

// Before a case starts: the demands found in a sheet, and what each one is still missing. The person fills a gap,
// asks the requester for it, or starts anyway (an incomplete demand is then held and returned for information).
// A value shared by several demands is applied only to the demands the person picks: nothing is assumed to be shared.

function FieldInput({ field, value, onChange, disabled }) {
  if (field.type === 'enum') {
    return (
      <select className="rq-in" aria-label={field.label} value={value} disabled={disabled} onChange={e => onChange(e.target.value)}>
        <option value="">Choose…</option>
        {field.values.map(v => <option key={v} value={v}>{v}</option>)}
      </select>
    )
  }
  if (field.type === 'textarea') {
    return <textarea className="rq-in" aria-label={field.label} rows={3} value={value} disabled={disabled} onChange={e => onChange(e.target.value)} />
  }
  return <input className="rq-in" aria-label={field.label} value={value} disabled={disabled} onChange={e => onChange(e.target.value)} />
}

function Group({ g, field, ids, titles, busy, run }) {
  const [value, setValue] = useState('')
  const [picked, setPicked] = useState(() => new Set(g.items))
  const chosen = g.items.filter(i => picked.has(i))
  const toggle = (id) => setPicked(p => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n })
  return (
    <div className="cs-card rq-group">
      <div><b>{g.label}</b> is missing in {g.items.length} {g.items.length === 1 ? ids.singular : ids.plural}.
        {g.description && <small className="rq-help"> {g.description}</small>}</div>
      <div className="rq-picks">{g.items.map(i => (
        <label key={i} className="rq-pick"><input type="checkbox" checked={picked.has(i)} onChange={() => toggle(i)} />{i}{titles[i] ? ' · ' + titles[i] : ''}</label>))}</div>
      <FieldInput field={field} value={value} onChange={setValue} disabled={busy} />
      <div className="cs-actions">
        <button className="btn sm primary" disabled={busy || !value.trim() || !chosen.length}
          onClick={() => run(() => api.requestFill(g.rid, { field: g.field, items: chosen, value }))}>Fill in the {chosen.length} chosen</button>
        <button className="btn sm" disabled={busy || !chosen.length}
          onClick={() => run(() => api.requestFill(g.rid, { field: g.field, items: chosen, decline: true }))}>Ask the requesters for the {chosen.length} chosen</button>
      </div>
    </div>
  )
}

function Demand({ req, it, fields, busy, run }) {
  const [vals, setVals] = useState({})
  const [decl, setDecl] = useState(() => new Set(it.declined))
  const byName = Object.fromEntries(fields.map(f => [f.name, f]))
  const incomplete = it.missing.length > 0 || it.problems.length > 0
  const dirty = Object.values(vals).some(v => v.trim()) || it.missing.some(m => decl.has(m.name) !== it.declined.includes(m.name))
  const save = () => run(() => api.requestSet(req.id, it.id, {
    values: Object.fromEntries(Object.entries(vals).filter(([, v]) => v.trim())),
    declined: it.missing.filter(m => decl.has(m.name) && !(vals[m.name] || '').trim()).map(m => m.name),
  }))
  const toggleDecl = (name) => setDecl(d => { const n = new Set(d); if (n.has(name)) n.delete(name); else n.add(name); return n })
  return (
    <details className="rq-item" open={incomplete && it.missing.length <= 4}>
      <summary>
        <span className="rq-id">{it.id}</span><span className="rq-title">{it.title}</span>
        {it.problems.length > 0 ? <span className="cs-pill crit">ID problem</span>
          : it.missing.length === 0 ? <span className="cs-pill ok">Complete</span>
            : <span className="cs-pill warn">Missing {it.missing.length}</span>}
      </summary>
      <div className="rq-body">
        {it.problems.map(p => <div key={p} className="cs-need">{p}</div>)}
        {it.missing.length === 0 && it.problems.length === 0 && <div className="cs-muted">Everything required is filled in.</div>}
        {it.missing.map(m => (
          <div key={m.name} className="rq-field">
            <label>{m.label}</label>
            {byName[m.name] && byName[m.name].description && <small className="rq-help">{byName[m.name].description}</small>}
            <FieldInput field={byName[m.name] || { label: m.label, type: 'text', values: [] }} value={vals[m.name] || ''}
              onChange={v => setVals(s => ({ ...s, [m.name]: v }))} disabled={busy} />
            <label className="rq-ask"><input type="checkbox" checked={decl.has(m.name) && !(vals[m.name] || '').trim()} disabled={busy || !!(vals[m.name] || '').trim()}
              onChange={() => toggleDecl(m.name)} />Ask the requester for this</label>
          </div>))}
        {it.missing.length > 0 && <div className="cs-actions"><button className="btn sm primary" disabled={busy || !dirty} onClick={save}>Save</button></div>}
      </div>
    </details>
  )
}

export function RequestPanel({ req, busy, run, onStart, onBack }) {
  const s = req.summary
  const L = req.item_label
  const fields = Object.fromEntries(req.fields.map(f => [f.name, f]))
  const titles = Object.fromEntries(req.items.map(i => [i.id, i.title]))
  const many = (n) => `${n} ${n === 1 ? L.singular : L.plural}`
  return (
    <div className="rq">
      <div>
        <div className="eyebrow">Before we start</div>
        <h1 style={{ marginTop: 6 }}>{many(s.total)} found{req.files[0] ? ' in ' + req.files[0] : ''}</h1>
        <p className="cs-muted" style={{ maxWidth: '62ch' }}>
          {req.ready ? `Every required field is filled in.`
            : `${s.complete} complete. ${s.incomplete} still ${s.incomplete === 1 ? 'misses' : 'miss'} required information. Fill it in here, ask the ${s.incomplete === 1 ? 'requester' : 'requesters'}, or start anyway: an incomplete ${L.singular} is held and returned for information while the others carry on.`}
        </p>
        {req.unmatched.length > 0 && <p className="cs-muted" style={{ margin: '6px 0 0', fontSize: 13 }}>Columns not recognised and ignored: {req.unmatched.join(', ')}.</p>}
      </div>

      {req.groups.map(g => <Group key={g.field} g={{ ...g, rid: req.id }} field={fields[g.field]} ids={L} titles={titles} busy={busy} run={run} />)}

      <div className="rq-list">
        {req.items.map(it => <Demand key={it.id} req={req} it={it} fields={req.fields} busy={busy} run={run} />)}
      </div>

      <div className="cs-actions">
        {req.ready
          ? <button className="btn primary" disabled={busy} onClick={() => onStart(false)}>Start the case</button>
          : <button className="btn primary" disabled={busy || s.problems > 0} onClick={() => onStart(true)}>Start anyway, holding {many(s.incomplete)}</button>}
        {!req.ready && <a className="btn" href={api.requestGapsUrl(req.id)}>Download the gaps sheet</a>}
        <button className="btn" disabled={busy} onClick={onBack}>Back</button>
      </div>
      {s.problems > 0 && <div className="cs-need">Fix the ID problems first: two {L.plural} cannot share an ID.</div>}
    </div>
  )
}
