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

// The documents a kind of source stands for: those whose name holds every word of the kind (the same rule the server applies).
const words = (t) => new Set((String(t || '').toLowerCase().match(/[\p{L}\p{N}]{2,}/gu)) || [])
const resolveDocs = (kind, docs) => { const kw = [...words(kind)]; return kw.length ? docs.filter(d => { const dw = words(d); return kw.every(w => dw.has(w)) }) : [] }

// The lookups of a property as JSON. It only changes the use case when the text is valid.
function LookupsBox({ value, onValid }) {
  const [text, setText] = useState(JSON.stringify(value || [], null, 1))
  const [bad, setBad] = useState('')
  useEffect(() => { setText(JSON.stringify(value || [], null, 1)) }, [value])
  return (
    <div>
      <textarea style={{ width: '100%', minHeight: 90, fontFamily: 'var(--mono)', fontSize: 12, border: bad ? '1px solid var(--crit)' : undefined }} value={text}
        onChange={e => { setText(e.target.value); try { const v = JSON.parse(e.target.value || '[]'); if (!Array.isArray(v)) throw new Error('a list'); setBad(''); onValid(v) } catch (x) { setBad(String(x.message || x)) } }} />
      <div className="meta">{bad ? 'Not saved: ' + bad : 'Each lookup: find, from (systems, data, processes, users, mandates, projects, dates, tools_today, requested, need, all_text, other_demands), match (name, meaning, compare), in (kinds of source), types (kinds of entity), relations (graph relationships), pages (true: also pick wiki pages by title and summary), extract.'}</div>
    </div>
  )
}

const KINDS = ['application', 'data', 'technology', 'security', 'role']
const DIRECTIONS = [['out', 'outgoing (from the matched entity)'], ['in', 'incoming (to the matched entity)'], ['both', 'both directions']]

// Per lookup: which kinds of entity a name may be, and which graph relationships to read around the entity it matches.
// `edges` are the metamodel's relationship types (the graph holds no others); `counts` says how many edges of each the
// graph really holds, so the owner sees which carry anything; "Suggest" drafts a list for the owner to accept or change.
function LookupRelations({ lookups, edges, counts, col, pagesDefault, docs, onChange }) {
  const [sugg, setSugg] = useState({})            // lookup index -> { loading, status, items, error }
  const blank = () => ({ find: '', from: 'need', match: 'meaning', in: [] })
  if (!lookups || !lookups.length) return (
    <div style={{ display: 'grid', gap: 6 }}>
      <div className="meta">No lookups yet. Lookups are drafted from the steps when left empty.</div>
      <div><button type="button" className="btn add-lookup" onClick={() => onChange([blank()])}>+ lookup</button></div>
    </div>)
  const set = (li, fn) => { const next = structuredClone(lookups); fn(next[li]); if (!next[li].types?.length) delete next[li].types; if (!next[li].relations?.length) delete next[li].relations; onChange(next) }
  const edge = (k) => edges.find(e => e.key === k)
  const short = (ts) => [...new Set((ts || []).map(t => t.replace(/^(logical|physical)_/, '')))]
  const ends = (e) => e ? `${short(e.source_types).slice(0, 3).join(', ')}${short(e.source_types).length > 3 ? ', …' : ''}  →  ${short(e.target_types).slice(0, 3).join(', ')}${short(e.target_types).length > 3 ? ', …' : ''}` : ''
  // a definition is shown without the modelling-notation label some carry, e.g. "(ArchiMate Flow)"
  const clean = (t) => (t || '').replace(/\s*\([^()]*archimate[^()]*\)/gi, '').replace(/\s*\barchimate\b\s*/gi, ' ').trim()
  const haveGraph = !!counts && counts.edges > 0
  const total = (rel) => counts?.relations?.[rel]?.total || 0
  // edges the lookup would read: those at an entity of its kinds (any kind when none), in the direction chosen
  const readable = (rel, dir, kinds) => {
    const c = counts?.relations?.[rel]; if (!c) return 0
    const side = d => Object.entries(c[d] || {}).reduce((a, [k, v]) => a + (!kinds.length || kinds.includes(k) ? v : 0), 0)
    return dir === 'out' ? side('out') : dir === 'in' ? side('in') : side('out') + side('in')
  }
  async function suggest(li) {
    const lk = lookups[li]
    setSugg(s => ({ ...s, [li]: { loading: true } }))
    try {
      const r = await api.suggestRelations({ property: { name: col.name, description: col.description, how_to_resolve: col.how_to_resolve, rules: col.rules },
        lookup: { find: lk.find, from: lk.from, types: lk.types || [], in: lk.in || [], extract: lk.extract || '' } })
      setSugg(s => ({ ...s, [li]: { status: r.status, items: r.suggestions || [] } }))
    } catch (e) { setSugg(s => ({ ...s, [li]: { error: String(e).replace('Error: ', '') } })) }
  }
  const has = (lk, r) => (lk.relations || []).some(x => x.relation === r.relation && x.direction === r.direction)
  return (
    <div className="lookup-relations" style={{ display: 'grid', gap: 8, marginBottom: 8 }}>
      {counts && !haveGraph && <div className="meta">No graph is loaded, so edge counts are not available.</div>}
      {lookups.map((lk, li) => (
        <div key={li} style={{ border: '1px solid var(--line, #d8dde6)', borderRadius: 6, padding: 8, display: 'grid', gap: 6 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'space-between' }}>
            <div><b>{li + 1}.</b> <span className="meta">starts from {lk.from}, matches by {lk.match}{lk.in?.length ? ', looks in ' + lk.in.join(', ') : ''}</span></div>
            <button type="button" className="btn remove-lookup" style={{ color: 'var(--crit)' }}
              onClick={() => { if (confirm(`Remove lookup ${li + 1}${lk.find ? ': "' + lk.find.slice(0, 60) + '"' : ''}?`)) onChange(lookups.filter((_, i) => i !== li)) }}>Remove this lookup</button>
          </div>
          <label className="meta" htmlFor={'q-' + li}>Question asked of the documents (the search is led by it)</label>
          <textarea id={'q-' + li} className="lookup-question" maxLength={200} rows={2} value={lk.find || ''}
            style={{ width: '100%', border: !(lk.find || '').trim() ? '1px solid var(--crit)' : undefined }}
            onChange={e => set(li, l => { l.find = e.target.value })} />
          <div className="meta lookup-preview">{!(lk.find || '').trim() ? 'A question is needed: this lookup is not saved without one.'
            : lk.match === 'name' && !['need', 'all_text', 'other_demands'].includes(lk.from)
              ? <>Searches for: “{lk.find.trim()}: <i>a name from the demand</i>”, and, when the name is an abbreviation, also with the official name of the entity found for it.</>
              : <>Searches for: “{lk.find.trim()}. <i>the opening words of the demand</i>”.</>}</div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            <span className="meta">A name may be a:</span>
            {KINDS.map(k => {
              const on = (lk.types || []).includes(k)
              return <button key={k} type="button" className={'btn' + (on ? ' primary' : '')} data-kind={k}
                onClick={() => set(li, l => { const cur = l.types || []; l.types = on ? cur.filter(x => x !== k) : [...cur, k] })}>{k}</button>
            })}
            <span className="meta">{(lk.types || []).length ? '' : '(any kind)'}</span>
          </div>
          {(lk.in || []).length > 0 && <div className="meta lookup-kinds" style={{ display: 'grid', gap: 2 }}>
            {lk.in.map(k => { const hit = resolveDocs(k, docs || []); return (
              <div key={k} style={{ color: hit.length ? undefined : 'var(--crit)' }}>
                “{k}” → {hit.length ? hit.join(', ') : 'no ingested document has all these words in its name, so every document is searched'}</div>) })}
          </div>}
          <label className="meta lookup-pages" style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
            <input type="checkbox" checked={lk.pages ?? pagesDefault} onChange={e => set(li, l => { l.pages = e.target.checked })} />
            <span>Also search the wiki pages. A model reads the title and first sentence of every wiki page and picks up to 3 that could answer the question above (for a mandate, a strategy or a roadmap, for example); those pages are read and cited. It works from the demand's words, so it also suits a lookup that starts from no name. Off: the wiki is read only for the names this lookup matches.{pagesDefault && lk.pages === undefined ? ' (On because the use case turns it on for every lookup.)' : ''}</span>
          </label>
          <div className="meta" style={{ marginTop: 2 }}>Graph relationships to read around each entity the name matches (one step){lk.match !== 'name' ? ' — only lookups that match by name read the graph' : ''}:</div>
          {(lk.relations || []).map((r, ri) => {
            const n = readable(r.relation, r.direction, lk.types || [])
            return (
              <div key={ri} style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }} className="relation-row">
                <select value={r.relation} onChange={e => set(li, l => { l.relations[ri].relation = e.target.value })} style={{ minWidth: 200, maxWidth: '100%' }}>
                  {!edge(r.relation) && <option value={r.relation}>{r.relation} (not in the metamodel)</option>}
                  {edges.map(e => <option key={e.key} value={e.key}>{e.key}{haveGraph ? `  (${total(e.key)} in the graph)` : ''}</option>)}
                </select>
                <select value={r.direction} onChange={e => set(li, l => { l.relations[ri].direction = e.target.value })}>
                  {DIRECTIONS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                </select>
                <button type="button" className="btn" aria-label="remove relationship" onClick={() => set(li, l => { l.relations.splice(ri, 1) })}>remove</button>
                {haveGraph && <span className="edge-count" style={{ color: n === 0 ? 'var(--crit)' : undefined, fontWeight: 600 }}>
                  {n === 0 ? 'no edges to read here' : `${n} edge${n === 1 ? '' : 's'} to read`}</span>}
                {edge(r.relation) && <span className="meta" style={{ flexBasis: '100%' }}>{ends(edge(r.relation))} — {clean(edge(r.relation).definition)}</span>}
              </div>
            )
          })}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <button type="button" className="btn add-relation" disabled={!edges.length}
              onClick={() => set(li, l => { l.relations = [...(l.relations || []), { relation: edges[0].key, direction: 'both' }] })}>+ relationship</button>
            {lk.match === 'name' && <button type="button" className="btn suggest-relations" disabled={!!sugg[li]?.loading || !col?.name} onClick={() => suggest(li)}>
              {sugg[li]?.loading ? 'Thinking…' : 'Suggest relationships'}</button>}
            {!(lk.relations || []).length && <span className="meta">None: the graph is not read for this lookup.</span>}
          </div>
          {sugg[li]?.error && <div className="meta" style={{ color: 'var(--crit)' }}>Could not suggest: {sugg[li].error}</div>}
          {sugg[li]?.status === 'unavailable' && <div className="meta" style={{ color: 'var(--crit)' }}>The model did not answer: no suggestion was made (this is not "none needed").</div>}
          {sugg[li]?.status === 'ok' && (
            <div className="suggestions" style={{ background: 'var(--bg-soft, #f3f6f9)', borderRadius: 6, padding: 8, display: 'grid', gap: 4 }}>
              <div className="meta">Suggested (a draft: nothing is added until you add it)</div>
              {!sugg[li].items.length && <div>No relationships suggested: the catalog and the wiki page answer this lookup.</div>}
              {sugg[li].items.map((r, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'baseline', paddingBottom: 6, borderBottom: '1px solid var(--line, #d8dde6)' }}>
                  <button type="button" className="btn add-suggestion" disabled={has(lk, r)} onClick={() => set(li, l => { l.relations = [...(l.relations || []), { relation: r.relation, direction: r.direction }] })}>{has(lk, r) ? 'added' : 'add'}</button>
                  <b>{r.relation}</b> <span>{DIRECTIONS.find(d => d[0] === r.direction)?.[1]}</span>
                  {haveGraph && <span style={{ color: r.edges === 0 ? 'var(--crit)' : undefined }}>{r.edges === 0 ? 'no edges to read' : `${r.edges} edges to read`}</span>}
                  <span className="meta" style={{ flexBasis: '100%' }}>{r.why}</span>
                </div>
              ))}
              {sugg[li].items.length > 1 && <div><button type="button" className="btn add-all-suggestions" onClick={() => set(li, l => { const cur = l.relations || []; l.relations = [...cur, ...sugg[li].items.filter(r => !has(l, r)).map(r => ({ relation: r.relation, direction: r.direction }))] })}>add all</button></div>}
            </div>
          )}
        </div>
      ))}
      <div><button type="button" className="btn add-lookup" disabled={lookups.length >= 6} onClick={() => onChange([...lookups, blank()])}>+ lookup</button>
        {lookups.length >= 6 && <span className="meta"> (at most 6 lookups per property)</span>}</div>
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
  const [counts, setCounts] = useState(null)    // how many edges of each type the graph holds
  const [page, setPage] = useState(null)        // the page of the builder being shown: { k: basics|input|gate|stage|prop, si, ci }
  const [hist, setHist] = useState(null)        // the history panel: { versions, store, diff }

  const reload = () => api.usecases().then(d => setList(d.usecases)).catch(e => setError(String(e)))
  useEffect(() => { reload(); api.docs().then(d => setDocs((d.docs || []).map(x => x.doc_id))).catch(() => {}); api.metamodel().then(m => setEdges(m.edge_types || [])).catch(() => {}); api.relationCounts().then(setCounts).catch(() => {}) }, [])

  const patch = (fn) => setUc(prev => { const d = structuredClone(prev); fn(d); return d })

  async function newUC() { setEditingId(null); setUc(BLANK()); setError(''); setPage({ k: 'basics' }); setHist(null) }
  async function edit(id) { setError(''); const s = await api.usecase(id); setEditingId(id); setUc(s); setPage({ k: 'basics' }); setHist(null) }
  async function openHistory() {
    try { const [v, diff] = await Promise.all([api.usecaseVersions(editingId), api.usecaseFileDiff(editingId)]); setHist({ versions: v.versions, store: v.store, diff }) }
    catch (e) { setError(String(e).replace('Error: ', '')) }
  }
  async function afterRestore(s) { setUc(s); await reload(); await openHistory() }
  async function restoreVersion(v) {
    if (!confirm('Put back the settings saved on ' + new Date(v.saved_at * 1000).toLocaleString() + '? The current ones stay in the history.')) return
    try { await afterRestore(await api.restoreUsecase(editingId, v.vid)) } catch (e) { setError(String(e).replace('Error: ', '')) }
  }
  async function loadFromFile() {
    if (!confirm('Replace the saved settings with the file that came with the code? The current ones stay in the history.')) return
    try { await afterRestore(await api.loadUsecaseFromFile(editingId)) } catch (e) { setError(String(e).replace('Error: ', '')) }
  }
  async function save() {
    setSaving(true); setError('')
    try {
      // normalize enum values (comma string -> array handled inline already)
      if (editingId) await api.updateUsecase(editingId, uc)
      else await api.createUsecase(uc)
      setUc(null); setEditingId(null); setPage(null); setHist(null); await reload()
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

  // ---------- BUILDER MODE: one page at a time ----------
  const inp = { width: '100%', padding: '7px 10px', border: '1px solid var(--border)', borderRadius: 7, background: 'var(--bg)', color: 'var(--fg)', fontSize: 13, fontFamily: 'inherit' }
  const h = { fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.05em', color: 'var(--fg-faint)', margin: '0 0 10px' }
  const card = { padding: 16, marginBottom: 14 }
  const lab = { display: 'block', marginTop: 10 }
  const sel = page || { k: 'basics' }
  const props = uc.stages.flatMap((s, si) => s.output.columns.map((c, ci) => ({ si, ci, c })))
  const badKinds = (c) => (c.lookups || []).reduce((n, lk) => n + (lk.in || []).filter(k => !resolveDocs(k, docs).length).length, 0)
  const patchCol = (si, ci, fn) => patch(d => fn(d.stages[si].output.columns[ci]))
  const isSel = (k, si, ci) => sel.k === k && sel.si === si && sel.ci === ci
  const pos = props.findIndex(x => sel.k === 'prop' && x.si === sel.si && x.ci === sel.ci)
  const nav = (k, si, ci, text, note) => (
    <button key={`${k}-${si}-${ci}`} type="button" className={'btn uc-nav' + (isSel(k, si, ci) ? ' primary' : '')} style={{ textAlign: 'left', justifyContent: 'flex-start', width: '100%' }}
      onClick={() => setPage({ k, si, ci })}>{text}{note ? <span style={{ marginLeft: 'auto', paddingLeft: 8, opacity: .8 }}>{note}</span> : null}</button>)
  const toggle = (arr, v) => arr.includes(v) ? arr.filter(x => x !== v) : [...arr, v]

  function PropertyPage({ si, ci, c }) {
    const s = uc.stages[si]
    const set = (fn) => patchCol(si, ci, fn)
    const text = (key, rows, ph, max) => <textarea style={{ ...inp, minHeight: rows }} maxLength={max || 2500} placeholder={ph} value={c[key] || ''}
      onChange={e => set(col => { if (e.target.value) col[key] = e.target.value; else delete col[key] })} />
    return (
      <div className="uc-property">
        <div className="card" style={card}>
          <div style={h}>What it is</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <input style={{ ...inp, flex: 2, minWidth: 160 }} placeholder="property name" value={c.name} onChange={e => set(col => { col.name = e.target.value })} />
            <select style={{ ...inp, flex: 1, minWidth: 110 }} value={c.type} onChange={e => set(col => { col.type = e.target.value })}>
              {COLUMN_TYPES.map(t => <option key={t}>{t}</option>)}
            </select>
          </div>
          {c.type === 'enum' && <input style={{ ...inp, marginTop: 8 }} placeholder="values, comma-separated" value={(c.values || []).join(', ')}
            onChange={e => set(col => { col.values = e.target.value.split(',').map(x => x.trim()).filter(Boolean) })} />}
          <label className="meta" style={lab}>What it means (the agent reads this)</label>
          <textarea style={{ ...inp, minHeight: 60 }} maxLength={DESC_MAX} value={c.description || ''} onChange={e => set(col => { col.description = e.target.value })} />
          <label className="meta" style={lab}>The short sentence shown while it is worked</label>
          <input style={inp} maxLength={80} placeholder="for example: Classifying domains" value={c.activity || ''} onChange={e => set(col => { col.activity = e.target.value })} />
        </div>

        <div className="card" style={card}>
          <div style={h}>How to decide it</div>
          <label className="meta">How to resolve: the steps, in order</label>
          <textarea style={{ ...inp, minHeight: 90 }} maxLength={DESC_MAX} value={c.how_to_resolve || ''} onChange={e => set(col => { col.how_to_resolve = e.target.value })} />
          <label className="meta" style={lab}>Rules and decision criteria</label>
          {text('rules', 60, 'Rules / decision criteria for this property')}
          <label className="meta" style={lab}>Examples: one right, one wrong (to show the format and the reasoning, never to copy)</label>
          {text('examples', 50, 'Examples')}
          <label className="meta" style={lab}>Combine the evidence: the last points, on how to read what was retrieved (which source wins, what is enough, when to ask)</label>
          <textarea className="collate" style={{ ...inp, minHeight: 80 }} maxLength={2500} value={c.collate || ''}
            onChange={e => set(col => { if (e.target.value) col.collate = e.target.value; else delete col.collate })} />
        </div>

        <div className="card" style={card}>
          <div style={h}>Where to look</div>
          <label className="meta">The kinds of source, as the steps name them (not file names: a new document of the right kind is found without editing this)</label>
          {text('where_to_look', 50, 'for example: Application Catalog, Business Capability Map')}
          <label className="meta" style={lab}>Look first in these documents</label>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {docs.length === 0 && <span className="meta">No documents ingested yet.</span>}
            {docs.map(dn => { const on = (c.look_in || []).includes(dn)
              return <button key={dn} type="button" className={'btn' + (on ? ' primary' : '')} onClick={() => set(col => { col.look_in = toggle(col.look_in || [], dn) })}>{dn}</button> })}
          </div>
        </div>

        <div className="card" style={card}>
          <div style={h}>Lookups: what is searched for, and where</div>
          <div className="meta" style={{ marginBottom: 6 }}>Each lookup asks one question of the wiki, the graph and the documents. A kind of source under “in” is matched to the ingested documents by the words in their names.</div>
          <LookupRelations lookups={c.lookups} edges={edges} counts={counts} col={c} pagesDefault={!!uc.wiki_pages} docs={docs}
            onChange={v => set(col => { col.lookups = v })} />
          <details>
            <summary className="meta" style={{ cursor: 'pointer' }}>The lookups as JSON (to add or change a lookup)</summary>
            <LookupsBox value={c.lookups} onValid={v => set(col => { if (v && v.length) col.lookups = v; else delete col.lookups })} />
          </details>
        </div>

        <div className="card" style={card}>
          <div style={h}>Evidence and questions</div>
          <label style={{ display: 'flex', gap: 7, alignItems: 'center', fontSize: 13 }}>
            <input type="checkbox" checked={c.evidence_required !== false} onChange={e => set(col => { col.evidence_required = e.target.checked })} />
            A cited source is required (if none is found, the architect is asked)
          </label>
          <label style={{ display: 'flex', gap: 7, alignItems: 'flex-start', fontSize: 13, marginTop: 8 }}>
            <input type="checkbox" checked={!!c.blank_ok} onChange={e => set(col => { if (e.target.checked) col.blank_ok = true; else delete col.blank_ok })} />
            <span>No result is a valid answer: when nothing is found the property is “None” and the architect is not asked (for example, the number of a duplicate demand when there is no duplicate). A text property only.</span>
          </label>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginTop: 10 }}>
            <span className="meta">Minimum cited sources</span>
            <input type="number" min={1} max={5} style={{ ...inp, width: 70 }} value={c.min_sources || ''}
              onChange={e => set(col => { const v = parseInt(e.target.value, 10); if (v) col.min_sources = v; else delete col.min_sources })} />
            <span className="meta">(1 for a fact copied from a register, 2 for a judgment)</span>
          </div>
          <label className="meta" style={lab}>When the INPUT is missing: what to ask the requester</label>
          <input style={inp} maxLength={300} value={c.info_needed || ''} onChange={e => set(col => { col.info_needed = e.target.value })} />
          <label className="meta" style={lab}>When a SOURCE is missing: what to say and whom to ask</label>
          <input style={inp} maxLength={300} value={c.info_needed_source || ''} onChange={e => set(col => { col.info_needed_source = e.target.value })} />
        </div>

        {s.output.columns.length > 1 && <div className="card" style={card}>
          <div style={h}>Builds on (decided first)</div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {s.output.columns.filter((o, oi) => oi !== ci && o.name).map(o => (
              <button key={o.name} type="button" className={'btn' + ((c.uses || []).includes(o.name) ? ' primary' : '')}
                onClick={() => set(col => { col.uses = toggle(col.uses || [], o.name) })}>{o.name}</button>))}
          </div>
        </div>}

        <div style={{ display: 'flex', gap: 8, justifyContent: 'space-between', marginBottom: 30 }}>
          <button className="btn" disabled={pos <= 0} onClick={() => setPage({ k: 'prop', si: props[pos - 1].si, ci: props[pos - 1].ci })}>← Previous property</button>
          <button className="btn" style={{ color: 'var(--crit)' }} onClick={() => { if (confirm(`Remove the property "${c.name || 'new property'}"?`)) { patch(d => d.stages[si].output.columns.splice(ci, 1)); setPage({ k: 'stage', si }) } }}>Remove this property</button>
          <button className="btn" disabled={pos < 0 || pos >= props.length - 1} onClick={() => setPage({ k: 'prop', si: props[pos + 1].si, ci: props[pos + 1].ci })}>Next property →</button>
        </div>
      </div>
    )
  }

  const body = (() => {
    if (sel.k === 'basics') return (
      <div className="card" style={card}>
        <div style={h}>Basics</div>
        <label className="meta">Name</label>
        <input style={inp} value={uc.name} onChange={e => patch(d => { d.name = e.target.value })} />
        <label className="meta" style={lab}>Description</label>
        <textarea style={{ ...inp, minHeight: 50 }} value={uc.description} onChange={e => patch(d => { d.description = e.target.value })} />
        <label className="meta" style={lab}>Rules for every property (read by the agent for each one, for example: never approve or reject; roles, never names)</label>
        <textarea style={{ ...inp, minHeight: 60 }} maxLength={4000} value={uc.playbook || ''} onChange={e => patch(d => { d.playbook = e.target.value })} />
        <label style={{ display: 'flex', gap: 7, alignItems: 'center', marginTop: 10, fontSize: 13 }}>
          <input type="checkbox" checked={uc.enabled} onChange={e => patch(d => { d.enabled = e.target.checked })} /> Enabled
        </label>
        <label style={{ display: 'flex', gap: 7, alignItems: 'flex-start', marginTop: 10, fontSize: 13 }}>
          <input type="checkbox" checked={!!uc.wiki_pages} onChange={e => patch(d => { if (e.target.checked) d.wiki_pages = true; else delete d.wiki_pages })} />
          <span>Search the wiki pages for every lookup (a model picks pages from their titles and first sentences). A lookup can still turn it off for itself.</span>
        </label>
        <label style={{ display: 'flex', gap: 7, alignItems: 'flex-start', marginTop: 10, fontSize: 13 }}>
          <input type="checkbox" checked={uc.read_images !== false} onChange={e => patch(d => { if (e.target.checked) delete d.read_images; else d.read_images = false })} />
          <span>Show the image of a diagram to a vision model when the diagram is among the passages found (at most 2 per property). The model writes down what the diagram says about the question; the answer sees that beside the diagram's description. Off: only the description is used.</span>
        </label>
      </div>)
    if (sel.k === 'input') return (
      <div className="card" style={card}>
        <div style={h}>Input (what the user or the sheet provides)</div>
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
              <input style={{ ...inp, flex: 2 }} placeholder="field name" value={f.name} onChange={e => patch(d => { d.input.item_fields[i].name = e.target.value })} />
              <select style={{ ...inp, flex: 1 }} value={f.type} onChange={e => patch(d => { d.input.item_fields[i].type = e.target.value })}>
                {FIELD_TYPES.map(t => <option key={t}>{t}</option>)}
              </select>
              <label style={{ display: 'flex', gap: 5, alignItems: 'center', fontSize: 12, whiteSpace: 'nowrap' }}>
                <input type="checkbox" checked={!!f.required} onChange={e => patch(d => { d.input.item_fields[i].required = e.target.checked })} /> required
              </label>
              <button className="btn" onClick={() => patch(d => { d.input.item_fields.splice(i, 1) })}>✕</button>
            </div>
            <textarea style={{ ...inp, minHeight: 38 }} placeholder="Description: what this field holds and how to read it (optional)"
              maxLength={DESC_MAX} value={f.description || ''} onChange={e => patch(d => { d.input.item_fields[i].description = e.target.value })} />
          </div>
        ))}
        <button className="btn" onClick={() => patch(d => { d.input.item_fields.push({ name: '', type: 'text', required: false }) })}>+ field</button>
        <label style={{ display: 'flex', gap: 7, alignItems: 'center', marginTop: 12, fontSize: 13 }}>
          <input type="checkbox" checked={uc.input.accepts_file} onChange={e => patch(d => { d.input.accepts_file = e.target.checked })} /> Accept a CSV / Excel batch
        </label>
      </div>)
    if (sel.k === 'gate') return (
      <div className="card" style={{ ...card, borderLeft: '3px solid var(--warn)' }}>
        <div style={h}>Validation gate ⚠ runs first — if it fails, no stage runs</div>
        <label style={{ display: 'flex', gap: 7, alignItems: 'center', fontSize: 13, marginBottom: 10 }}>
          <input type="checkbox" checked={uc.validation.enabled} onChange={e => patch(d => { d.validation.enabled = e.target.checked })} /> Enabled
        </label>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 10 }}>
          <span className="meta">On fail:</span>
          <select style={{ ...inp, width: 160 }} value={uc.validation.on_fail} onChange={e => patch(d => { d.validation.on_fail = e.target.value })}>
            <option value="stop">Stop &amp; return reason</option>
            <option value="warn">Warn &amp; continue</option>
          </select>
        </div>
        <label className="meta">Intake questions (all must pass)</label>
        {uc.validation.questions.map((q, i) => (
          <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 6 }}>
            <input style={inp} value={q} onChange={e => patch(d => { d.validation.questions[i] = e.target.value })} />
            <button className="btn" onClick={() => patch(d => { d.validation.questions.splice(i, 1) })}>✕</button>
          </div>
        ))}
        <button className="btn" onClick={() => patch(d => { d.validation.questions.push('') })}>+ question</button>
        <label className="meta" style={{ ...lab, marginTop: 12 }}>Fail message</label>
        <input style={inp} value={uc.validation.fail_message} onChange={e => patch(d => { d.validation.fail_message = e.target.value })} />
      </div>)
    if (sel.k === 'stage') { const s = uc.stages[sel.si]; return s ? (
      <div className="card" style={card}>
        <div style={h}>Stage {sel.si + 1}</div>
        <label className="meta">Stage name</label>
        <input style={inp} value={s.name} onChange={e => patch(d => { d.stages[sel.si].name = e.target.value })} />
        <label className="meta" style={lab}>Instructions (what the agent should do)</label>
        <textarea style={{ ...inp, minHeight: 70 }} value={s.instructions} onChange={e => patch(d => { d.stages[sel.si].instructions = e.target.value })} />
        <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
          <button className="btn" onClick={() => { patch(d => { d.stages[sel.si].output.columns.push({ name: '', type: 'text', values: [] }) }); setPage({ k: 'prop', si: sel.si, ci: s.output.columns.length }) }}>+ property</button>
          {uc.stages.length > 1 && <button className="btn" style={{ color: 'var(--crit)' }} onClick={() => { if (confirm(`Remove stage ${sel.si + 1} and its properties?`)) { patch(d => { d.stages.splice(sel.si, 1) }); setPage({ k: 'basics' }) } }}>Remove this stage</button>}
        </div>
      </div>) : null }
    if (sel.k === 'prop') { const c = uc.stages[sel.si]?.output.columns[sel.ci]; return c ? PropertyPage({ si: sel.si, ci: sel.ci, c }) : null }   // called, not mounted: it is defined here, so mounting it would reset the focus on every keystroke
    return null
  })()

  return (
    <div className="wrap" style={{ maxWidth: 1180 }}>
      <div className="view-head">
        <div><div className="eyebrow">{editingId ? 'Edit' : 'New'} use case</div>
          <h1>{uc.name || 'Untitled use case'}</h1></div>
        <div style={{ display: 'flex', gap: 8 }}>
          {editingId && <button className="btn" onClick={openHistory}>History</button>}
          <button className="btn" onClick={() => { setUc(null); setEditingId(null); setPage(null); setHist(null) }}>Cancel</button>
          <button className="btn primary" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
        </div>
      </div>
      {error && <div className="card" style={{ padding: 12, color: 'var(--crit)', marginBottom: 14 }}>{error}</div>}

      {hist && (
        <div className="card uc-history" style={{ ...card, borderLeft: '3px solid var(--accent, #3b82f6)' }}>
          <div style={h}>History of the saved settings</div>
          {hist.store !== 'postgres' && <div className="meta" style={{ color: 'var(--crit)', marginBottom: 8 }}>
            {hist.store === 'files' ? 'These settings are kept in a file on this server’s own disk: a redeploy or restart replaces them with the file that came with the code.'
              : 'These settings are kept in a database file on this server’s own disk: a redeploy or restart loses them. Set HISTORY_BACKEND=postgres to keep them.'}</div>}
          {hist.diff && hist.diff.in_file && (hist.diff.changed.length || hist.diff.added.length || hist.diff.removed.length || hist.diff.other.length) ? (
            <div style={{ marginBottom: 10 }}>
              <div className="meta">The file that came with the code differs from the saved settings:</div>
              {hist.diff.changed.length > 0 && <div className="meta">Changed in the file: {hist.diff.changed.join('; ')}</div>}
              {hist.diff.added.length > 0 && <div className="meta">Only in the file: {hist.diff.added.join('; ')}</div>}
              {hist.diff.removed.length > 0 && <div className="meta">Only in the saved settings: {hist.diff.removed.join('; ')}</div>}
              {hist.diff.other.length > 0 && <div className="meta">Other settings that differ: {hist.diff.other.join(', ')}</div>}
              <button className="btn" style={{ marginTop: 6 }} onClick={loadFromFile}>Replace the saved settings with the file’s (the current ones stay in the history)</button>
            </div>) : hist.diff && hist.diff.in_file ? <div className="meta" style={{ marginBottom: 8 }}>The saved settings are the same as the file that came with the code.</div> : null}
          {hist.versions.length === 0 && <div className="meta">No earlier versions are kept (the settings are stored in files).</div>}
          {hist.versions.map(v => (
            <div key={v.vid} style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
              <span style={{ minWidth: 150 }}>{new Date(v.saved_at * 1000).toLocaleString()}</span>
              <span className="pill neutral">v{v.version}</span>
              <span className="meta" style={{ flex: 1 }}>{v.note}</span>
              <button className="btn" onClick={() => restoreVersion(v)}>Put back</button>
            </div>))}
          <div style={{ marginTop: 8 }}><button className="btn" onClick={() => setHist(null)}>Close</button></div>
        </div>
      )}

      <div className="uc-layout" style={{ display: 'grid', gridTemplateColumns: 'minmax(180px, 250px) minmax(0, 1fr)', gap: 18, alignItems: 'start' }}>
        <nav className="uc-sidebar" style={{ display: 'grid', gap: 4, position: 'sticky', top: 12 }}>
          {nav('basics', undefined, undefined, 'Basics')}
          {nav('input', undefined, undefined, 'Input')}
          {nav('gate', undefined, undefined, 'Validation gate')}
          {uc.stages.map((s, si) => (
            <div key={si} style={{ display: 'grid', gap: 4, marginTop: 8 }}>
              {nav('stage', si, undefined, `Stage ${si + 1}: ${s.name || 'untitled'}`)}
              {s.output.columns.map((c, ci) => {
                const bad = badKinds(c)
                return nav('prop', si, ci, '   ' + (c.name || '(new property)'), bad ? '⚠' : (c.lookups || []).length ? (c.lookups.length + ' lookups') : '')
              })}
            </div>
          ))}
          <button className="btn" style={{ marginTop: 8 }} onClick={() => { patch(d => { d.stages.push({ name: '', instructions: '', output: { mode: 'table', columns: [{ name: '', type: 'text', values: [] }] } }) }); setPage({ k: 'stage', si: uc.stages.length }) }}>+ add stage</button>
        </nav>
        <main className="uc-page" style={{ minWidth: 0 }}>{body}</main>
      </div>
      <div style={{ height: 40 }} />
    </div>
  )
}
