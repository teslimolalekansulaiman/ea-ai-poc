import { useEffect, useState } from 'react'
import { api } from '../api'

const COLUMN_TYPES = ['text', 'textarea', 'list', 'enum', 'citations', 'bool', 'number']
const FIELD_TYPES = ['text', 'textarea', 'enum', 'number']
const DESC_MAX = 1500   // matches the limit the server enforces

const BLANK = () => ({
  name: '', description: '', enabled: true,
  input: { accepts_file: false, batch_text_field: '', item_fields: [{ name: '', type: 'text', label: '', required: false }] },
  validation: { enabled: true, on_fail: 'stop', fail_message: '', questions: [''] },
  stages: [{ name: '', instructions: '', output: { mode: 'table', columns: [{ name: '', type: 'text', values: [] }] } }],
})

export default function UseCases() {
  const [list, setList] = useState([])
  const [uc, setUc] = useState(null)          // null = list mode; object = editing
  const [editingId, setEditingId] = useState(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const reload = () => api.usecases().then(d => setList(d.usecases)).catch(e => setError(String(e)))
  useEffect(() => { reload() }, [])

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
        <label style={{ display: 'flex', gap: 7, alignItems: 'center', marginTop: 10, fontSize: 13 }}>
          <input type="checkbox" checked={uc.enabled} onChange={e => patch(d => d.enabled = e.target.checked)} /> Enabled
        </label>
      </div>

      {/* Input fields */}
      <div className="card" style={{ padding: 16, ...sec }}>
        <div style={h}>1 · Input (what the user / sheet provides)</div>
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
              placeholder="Description: what this column means, where to look and how to decide it (the agent reads this)"
              maxLength={DESC_MAX} value={c.description || ''}
              onChange={e => patch(d => d.stages[si].output.columns[ci].description = e.target.value)} />
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
