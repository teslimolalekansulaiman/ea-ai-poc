import { useEffect, useState } from 'react'
import { api } from '../api'

const COLUMN_TYPES = ['text', 'textarea', 'list', 'enum', 'citations', 'bool', 'number']
const FIELD_TYPES = ['text', 'textarea', 'enum', 'number']
const DESC_MAX = 2500   // matches the limit the server enforces

const BLANK = () => ({
  name: '', description: '', enabled: true,
  input: { accepts_file: false, batch_text_field: '', item_fields: [{ name: '', type: 'text', label: '', required: false }] },
  validation: { enabled: true, on_fail: 'stop', fail_message: '', questions: [''] },
  stages: [{ name: '', instructions: '', output: { mode: 'table', columns: [{ name: '', type: 'text', values: [] }] } }],
})

// The lookups of a property as JSON. It only changes the use case when the text is valid.
function LookupsBox({ value, onValid }) {
  const [text, setText] = useState(JSON.stringify(value || [], null, 1))
  const [bad, setBad] = useState('')
  useEffect(() => { setText(JSON.stringify(value || [], null, 1)) }, [value])
  return (
    <div>
      <textarea style={{ width: '100%', minHeight: 90, fontFamily: 'var(--mono)', fontSize: 12, border: bad ? '1px solid var(--crit)' : undefined }} value={text}
        onChange={e => { setText(e.target.value); try { const v = JSON.parse(e.target.value || '[]'); if (!Array.isArray(v)) throw new Error('a list'); setBad(''); onValid(v) } catch (x) { setBad(String(x.message || x)) } }} />
      <div className="meta">{bad ? 'Not saved: ' + bad : 'Each lookup: find, from (systems, data, processes, users, mandates, projects, dates, tools_today, requested, need, all_text, other_demands), match (name, meaning, compare), in (kinds of source), types (kinds of entity), relations (graph relationships), extract.'}</div>
    </div>
  )
}

const KINDS = ['application', 'data', 'technology', 'security', 'role']
const DIRECTIONS = [['out', 'outgoing (from the matched entity)'], ['in', 'incoming (to the matched entity)'], ['both', 'both directions']]

// Per lookup: which kinds of entity a name may be, and which graph relationships to read around the entity it matches.
// `edges` are the metamodel's relationship types (the graph holds no others).
function LookupRelations({ lookups, edges, onChange }) {
  if (!lookups || !lookups.length) return <div className="meta">No lookups yet. Lookups are drafted from the steps when left empty; add them below as JSON to define their graph relationships.</div>
  const set = (li, fn) => { const next = structuredClone(lookups); fn(next[li]); if (!next[li].types?.length) delete next[li].types; if (!next[li].relations?.length) delete next[li].relations; onChange(next) }
  const edge = (k) => edges.find(e => e.key === k)
  const short = (ts) => [...new Set((ts || []).map(t => t.replace(/^(logical|physical)_/, '')))]
  const ends = (e) => e ? `${short(e.source_types).slice(0, 3).join(', ')}${short(e.source_types).length > 3 ? ', …' : ''}  →  ${short(e.target_types).slice(0, 3).join(', ')}${short(e.target_types).length > 3 ? ', …' : ''}` : ''
  return (
    <div className="lookup-relations" style={{ display: 'grid', gap: 8, marginBottom: 8 }}>
      {lookups.map((lk, li) => (
        <div key={li} style={{ border: '1px solid var(--line, #d8dde6)', borderRadius: 6, padding: 8, display: 'grid', gap: 6 }}>
          <div><b>{li + 1}.</b> {lk.find} <span className="meta">(from {lk.from}, match {lk.match}{lk.in?.length ? ', in ' + lk.in.join(', ') : ''})</span></div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            <span className="meta">A name may be a:</span>
            {KINDS.map(k => {
              const on = (lk.types || []).includes(k)
              return <button key={k} type="button" className={'btn' + (on ? ' primary' : '')} data-kind={k}
                onClick={() => set(li, l => { const cur = l.types || []; l.types = on ? cur.filter(x => x !== k) : [...cur, k] })}>{k}</button>
            })}
            <span className="meta">{(lk.types || []).length ? '' : '(any kind)'}</span>
          </div>
          <div className="meta" style={{ marginTop: 2 }}>Graph relationships to read around each entity the name matches (one step){lk.match !== 'name' ? ' — read for lookups that match by name' : ''}:</div>
          {(lk.relations || []).map((r, ri) => (
            <div key={ri} style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }} className="relation-row">
              <select value={r.relation} onChange={e => set(li, l => { l.relations[ri].relation = e.target.value })} style={{ minWidth: 200, maxWidth: '100%' }}>
                {!edge(r.relation) && <option value={r.relation}>{r.relation} (not in the metamodel)</option>}
                {edges.map(e => <option key={e.key} value={e.key}>{e.key}</option>)}
              </select>
              <select value={r.direction} onChange={e => set(li, l => { l.relations[ri].direction = e.target.value })}>
                {DIRECTIONS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
              </select>
              <button type="button" className="btn" aria-label="remove relationship" onClick={() => set(li, l => { l.relations.splice(ri, 1) })}>remove</button>
              {edge(r.relation) && <span className="meta" style={{ flexBasis: '100%' }}>{ends(edge(r.relation))} — {edge(r.relation).definition}</span>}
            </div>
          ))}
          <div><button type="button" className="btn add-relation" disabled={!edges.length}
            onClick={() => set(li, l => { l.relations = [...(l.relations || []), { relation: edges[0].key, direction: 'both' }] })}>+ relationship</button>
            {!(lk.relations || []).length && <span className="meta" style={{ marginLeft: 8 }}>None: the graph is not read for this lookup.</span>}</div>
        </div>
      ))}
    </div>
  )
}

export default function UseCases() {
  const [list, setList] = useState([])
  const [uc, setUc] = useState(null)          // null = list mode; object = editing
  const [editingId, setEditingId] = useState(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [docs, setDocs] = useState([])          // ingested documents a property can point to
  const [edges, setEdges] = useState([])        // the metamodel's relationship types, for the graph relationships of a lookup

  const reload = () => api.usecases().then(d => setList(d.usecases)).catch(e => setError(String(e)))
  useEffect(() => { reload(); api.docs().then(d => setDocs((d.docs || []).map(x => x.doc_id))).catch(() => {}); api.metamodel().then(m => setEdges(m.edge_types || [])).catch(() => {}) }, [])

  const patch = (fn) => setUc(prev => { const d = structuredClone(prev); fn(d); return d })

  async function newUC() { setEditingId(null); setUc(BLANK()); setError('') }
  async function edit(id) { setError(''); const s = await api.usecase(id); setEditingId(id); setUc(s) }
  async function save() {
    setSaving(true); setError('')
    try {
      // normalize enum values (comma string -> array handled inline already)
      if (editingId) await api.updateUsecase(editingId, uc)
      else await api.createUsecase(uc)
      setUc(null); setEditingId(null); await reload()
    } catch (e) { setError(String(e).replace('Error: ', '')) }
    setSaving(false)
  }
  async function remove(id) {
    if (!confirm(`Delete use case "${id}"? This cannot be undone.`)) return
    await api.deleteUsecase(id); await reload()
  }

  // ---------- LIST MODE ----------
  if (!uc) return (
    <div className="wrap">
      <div className="view-head">
        <div><div className="eyebrow">Configure</div><h1>Use cases</h1>
          <p>Define a use case: the questions to ask, the validation gate, and the output table columns. The AI chooses which knowledge to use.</p></div>
        <button className="btn primary" onClick={newUC}><span>+</span> New use case</button>
      </div>
      {error && <div className="card" style={{ padding: 12, color: 'var(--crit)', marginBottom: 14 }}>{error}</div>}
      <div className="kb-grid">
        {list.map(u => (
          <div className="card kb-doc" key={u.id}>
            <div className="top"><div><div className="nm">{u.name}</div>
              <div className="meta" style={{ color: 'var(--fg-muted)' }}>{u.description}</div></div></div>
            <div><span className={'pill ' + (u.enabled ? 'ok' : 'neutral')}>{u.enabled ? 'enabled' : 'disabled'}</span>
              {' '}<span className="pill neutral">{u.stages.length} stage(s)</span>
              {u.validation?.enabled && <span className="pill info"> validation gate</span>}</div>
            <div className="stats" style={{ gap: 10 }}>
              <a href={'#/run/' + u.id}>Run →</a>
              <a href="#" onClick={e => { e.preventDefault(); edit(u.id) }}>Edit</a>
              <a href="#" onClick={e => { e.preventDefault(); remove(u.id) }} style={{ color: 'var(--crit)' }}>Delete</a>
            </div>
          </div>
        ))}
        {list.length === 0 && <div className="empty">No use cases yet — create one.</div>}
      </div>
    </div>
  )

  // ---------- BUILDER MODE ----------
  const sec = { marginBottom: 18 }
  const h = { fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.05em', color: 'var(--fg-faint)', margin: '0 0 10px' }
  const inp = { width: '100%', padding: '7px 10px', border: '1px solid var(--border)', borderRadius: 7, background: 'var(--bg)', color: 'var(--fg)', fontSize: 13, fontFamily: 'inherit' }

  return (
    <div className="wrap" style={{ maxWidth: 900 }}>
      <div className="view-head">
        <div><div className="eyebrow">{editingId ? 'Edit' : 'New'} use case</div>
          <h1>{uc.name || 'Untitled use case'}</h1></div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn" onClick={() => { setUc(null); setEditingId(null) }}>Cancel</button>
          <button className="btn primary" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
        </div>
      </div>
      {error && <div className="card" style={{ padding: 12, color: 'var(--crit)', marginBottom: 14 }}>{error}</div>}

      {/* Basics */}
      <div className="card" style={{ padding: 16, ...sec }}>
        <div style={h}>Basics</div>
        <label className="meta">Name</label>
        <input style={inp} value={uc.name} onChange={e => patch(d => d.name = e.target.value)} />
        <label className="meta" style={{ marginTop: 10, display: 'block' }}>Description</label>
        <textarea style={{ ...inp, minHeight: 50 }} value={uc.description} onChange={e => patch(d => d.description = e.target.value)} />
        <label className="meta" style={{ marginTop: 10, display: 'block' }}>Rules for every property (read by the agent for each one, for example: never approve or reject; roles, never names)</label>
        <textarea style={{ ...inp, minHeight: 60 }} maxLength={4000} value={uc.playbook || ''} onChange={e => patch(d => d.playbook = e.target.value)} />
        <label style={{ display: 'flex', gap: 7, alignItems: 'center', marginTop: 10, fontSize: 13 }}>
          <input type="checkbox" checked={uc.enabled} onChange={e => patch(d => d.enabled = e.target.checked)} /> Enabled
        </label>
      </div>

      {/* Input fields */}
      <div className="card" style={{ padding: 16, ...sec }}>
        <div style={h}>1 · Input (what the user / sheet provides)</div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
          <span className="meta">What one input is called, singular and plural (shown on screen):</span>
          <input style={{ ...inp, width: 150 }} maxLength={40} placeholder="singular, e.g. demand" value={(uc.input.item_label || {}).singular || ''}
            onChange={e => patch(d => { d.input.item_label = { ...d.input.item_label, singular: e.target.value } })} />
          <input style={{ ...inp, width: 150 }} maxLength={40} placeholder="plural, e.g. demands" value={(uc.input.item_label || {}).plural || ''}
            onChange={e => patch(d => { d.input.item_label = { ...d.input.item_label, plural: e.target.value } })} />
        </div>
        {uc.input.item_fields.map((f, i) => (
          <div key={i} style={{ marginBottom: 10 }}>
          <div style={{ display: 'flex', gap: 8, marginBottom: 4 }}>
            <input style={{ ...inp, flex: 2 }} placeholder="field name" value={f.name} onChange={e => patch(d => d.input.item_fields[i].name = e.target.value)} />
            <select style={{ ...inp, flex: 1 }} value={f.type} onChange={e => patch(d => d.input.item_fields[i].type = e.target.value)}>
              {FIELD_TYPES.map(t => <option key={t}>{t}</option>)}
            </select>
            <label style={{ display: 'flex', gap: 5, alignItems: 'center', fontSize: 12, whiteSpace: 'nowrap' }}>
              <input type="checkbox" checked={!!f.required} onChange={e => patch(d => d.input.item_fields[i].required = e.target.checked)} /> required
            </label>
            <button className="btn" onClick={() => patch(d => d.input.item_fields.splice(i, 1))}>✕</button>
          </div>
          <textarea style={{ ...inp, minHeight: 38 }} placeholder="Description: what this field holds and how to read it (optional)"
            maxLength={DESC_MAX} value={f.description || ''} onChange={e => patch(d => d.input.item_fields[i].description = e.target.value)} />
          </div>
        ))}
        <button className="btn" onClick={() => patch(d => d.input.item_fields.push({ name: '', type: 'text', required: false }))}>+ field</button>
        <label style={{ display: 'flex', gap: 7, alignItems: 'center', marginTop: 12, fontSize: 13 }}>
          <input type="checkbox" checked={uc.input.accepts_file} onChange={e => patch(d => d.input.accepts_file = e.target.checked)} /> Accept a CSV / Excel batch
        </label>
      </div>

      {/* Validation gate */}
      <div className="card" style={{ padding: 16, ...sec, borderLeft: '3px solid var(--warn)' }}>
        <div style={h}>2 · Validation gate ⚠ runs first — if it fails, no stage runs</div>
        <label style={{ display: 'flex', gap: 7, alignItems: 'center', fontSize: 13, marginBottom: 10 }}>
          <input type="checkbox" checked={uc.validation.enabled} onChange={e => patch(d => d.validation.enabled = e.target.checked)} /> Enabled
        </label>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 10 }}>
          <span className="meta">On fail:</span>
          <select style={{ ...inp, width: 160 }} value={uc.validation.on_fail} onChange={e => patch(d => d.validation.on_fail = e.target.value)}>
            <option value="stop">Stop &amp; return reason</option>
            <option value="warn">Warn &amp; continue</option>
          </select>
        </div>
        <label className="meta">Intake questions (all must pass)</label>
        {uc.validation.questions.map((q, i) => (
          <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 6 }}>
            <input style={inp} value={q} onChange={e => patch(d => d.validation.questions[i] = e.target.value)} />
            <button className="btn" onClick={() => patch(d => d.validation.questions.splice(i, 1))}>✕</button>
          </div>
        ))}
        <button className="btn" onClick={() => patch(d => d.validation.questions.push(''))}>+ question</button>
        <label className="meta" style={{ marginTop: 12, display: 'block' }}>Fail message</label>
        <input style={inp} value={uc.validation.fail_message} onChange={e => patch(d => d.validation.fail_message = e.target.value)} />
      </div>

      {/* Stages */}
      <div style={h}>3 · Stages (run in order, only if validation passed)</div>
      {uc.stages.map((s, si) => (
        <div className="card" style={{ padding: 16, ...sec }} key={si}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <strong>Stage {si + 1}</strong>
            <button className="btn" onClick={() => patch(d => d.stages.splice(si, 1))}>✕ remove stage</button>
          </div>
          <label className="meta">Stage name</label>
          <input style={inp} value={s.name} onChange={e => patch(d => d.stages[si].name = e.target.value)} />
          <label className="meta" style={{ marginTop: 10, display: 'block' }}>Instructions (what the agent should do)</label>
          <textarea style={{ ...inp, minHeight: 70 }} value={s.instructions} onChange={e => patch(d => d.stages[si].instructions = e.target.value)} />
          <label className="meta" style={{ marginTop: 12, display: 'block' }}>Output columns (the result table)</label>
          {s.output.columns.map((c, ci) => (
            <div key={ci} style={{ marginBottom: 10 }}>
            <div style={{ display: 'flex', gap: 8, marginBottom: 4, flexWrap: 'wrap' }}>
              <input style={{ ...inp, flex: 2, minWidth: 140 }} placeholder="column name" value={c.name} onChange={e => patch(d => d.stages[si].output.columns[ci].name = e.target.value)} />
              <select style={{ ...inp, flex: 1, minWidth: 110 }} value={c.type} onChange={e => patch(d => d.stages[si].output.columns[ci].type = e.target.value)}>
                {COLUMN_TYPES.map(t => <option key={t}>{t}</option>)}
              </select>
              {c.type === 'enum' && (
                <input style={{ ...inp, flex: 2, minWidth: 140 }} placeholder="values, comma-separated"
                  value={(c.values || []).join(', ')}
                  onChange={e => patch(d => d.stages[si].output.columns[ci].values = e.target.value.split(',').map(x => x.trim()).filter(Boolean))} />
              )}
              <button className="btn" onClick={() => patch(d => d.stages[si].output.columns.splice(ci, 1))}>✕</button>
            </div>
            <textarea style={{ ...inp, minHeight: 38 }}
              placeholder="Description: what this column means (the agent reads this)"
              maxLength={DESC_MAX} value={c.description || ''}
              onChange={e => patch(d => d.stages[si].output.columns[ci].description = e.target.value)} />
            <details style={{ marginTop: 4 }}>
              <summary className="meta" style={{ cursor: 'pointer' }}>How to resolve, where to look, evidence</summary>
              <div style={{ display: 'grid', gap: 6, marginTop: 6 }}>
                <textarea style={{ ...inp, minHeight: 38 }} maxLength={DESC_MAX}
                  placeholder="How to resolve: how to decide the value, and any rule to apply"
                  value={c.how_to_resolve || ''}
                  onChange={e => patch(d => d.stages[si].output.columns[ci].how_to_resolve = e.target.value)} />
                <div className="meta">Look first in (documents):</div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {docs.length === 0 && <span className="meta">No documents ingested yet.</span>}
                  {docs.map(dn => {
                    const on = (c.look_in || []).includes(dn)
                    return <button key={dn} type="button" className={'btn' + (on ? ' primary' : '')}
                      onClick={() => patch(d => { const col = d.stages[si].output.columns[ci]; const cur = col.look_in || []; col.look_in = on ? cur.filter(x => x !== dn) : [...cur, dn] })}>{dn}</button>
                  })}
                </div>
                <label style={{ display: 'flex', gap: 7, alignItems: 'center', fontSize: 13 }}>
                  <input type="checkbox" checked={c.evidence_required !== false}
                    onChange={e => patch(d => { d.stages[si].output.columns[ci].evidence_required = e.target.checked })} />
                  A cited source is required (if none is found, the architect is asked)
                </label>
                <input style={inp} maxLength={80} placeholder="Activity: the short sentence shown while it is worked, e.g. Classifying domains"
                  value={c.activity || ''}
                  onChange={e => patch(d => d.stages[si].output.columns[ci].activity = e.target.value)} />
                <textarea style={{ ...inp, minHeight: 38 }} maxLength={2500} placeholder="Where to look: the kinds of source, as the steps name them (for example Application Catalog, Business Capability Map). Not file names: a new document of the right kind is found without editing this."
                  value={c.where_to_look || ''}
                  onChange={e => patch(d => d.stages[si].output.columns[ci].where_to_look = e.target.value)} />
                <textarea style={{ ...inp, minHeight: 38 }} maxLength={2500} placeholder="Rules / decision criteria for this property"
                  value={c.rules || ''}
                  onChange={e => patch(d => d.stages[si].output.columns[ci].rules = e.target.value)} />
                <textarea style={{ ...inp, minHeight: 38 }} maxLength={2500} placeholder="Examples: one correct, one wrong (the agent uses them to see the format and the reasoning, never to copy)"
                  value={c.examples || ''}
                  onChange={e => patch(d => d.stages[si].output.columns[ci].examples = e.target.value)} />
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <span className="meta">Minimum cited sources</span>
                  <input type="number" min={1} max={5} style={{ ...inp, width: 70 }} value={c.min_sources || ''}
                    onChange={e => patch(d => { const v = parseInt(e.target.value, 10); const col = d.stages[si].output.columns[ci]; if (v) col.min_sources = v; else delete col.min_sources })} />
                  <span className="meta">(1 for a fact copied from a register, 2 for a judgment)</span>
                </div>
                <input style={inp} maxLength={300} placeholder="Info needed when INPUT is missing: what to ask the requester"
                  value={c.info_needed || ''}
                  onChange={e => patch(d => d.stages[si].output.columns[ci].info_needed = e.target.value)} />
                <input style={inp} maxLength={300} placeholder="Info needed when a SOURCE is missing: what to say and whom to ask"
                  value={c.info_needed_source || ''}
                  onChange={e => patch(d => d.stages[si].output.columns[ci].info_needed_source = e.target.value)} />
                <details>
                  <summary className="meta" style={{ cursor: 'pointer' }}>Lookups (what the agent looks for; drafted from the steps when left empty)</summary>
                  <LookupRelations lookups={c.lookups} edges={edges} onChange={v => patch(d => { d.stages[si].output.columns[ci].lookups = v })} />
                  <div className="meta">The lookups as JSON (to add or change a lookup):</div>
                  <LookupsBox value={c.lookups} onValid={v => patch(d => { const col = d.stages[si].output.columns[ci]; if (v && v.length) col.lookups = v; else delete col.lookups })} />
                </details>
                {s.output.columns.length > 1 && (<>
                  <div className="meta">Builds on (decided first):</div>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {s.output.columns.filter((o, oi) => oi !== ci && o.name).map(o => {
                      const on = (c.uses || []).includes(o.name)
                      return <button key={o.name} type="button" className={'btn' + (on ? ' primary' : '')}
                        onClick={() => patch(d => { const col = d.stages[si].output.columns[ci]; const cur = col.uses || []; col.uses = on ? cur.filter(x => x !== o.name) : [...cur, o.name] })}>{o.name}</button>
                    })}
                  </div></>)}
              </div>
            </details>
            </div>
          ))}
          <button className="btn" onClick={() => patch(d => d.stages[si].output.columns.push({ name: '', type: 'text', values: [] }))}>+ column</button>
        </div>
      ))}
      <button className="btn" onClick={() => patch(d => d.stages.push({ name: '', instructions: '', output: { mode: 'table', columns: [{ name: '', type: 'text', values: [] }] } }))}>+ add stage</button>
      <div style={{ height: 40 }} />
    </div>
  )
}
