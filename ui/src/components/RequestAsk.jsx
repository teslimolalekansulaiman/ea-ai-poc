import { useEffect, useRef, useState } from 'react'

// What the request agent puts in front of the person, inside the chat: the open questions as a sheet to swipe through and answer
// once, the list shown when there are too many for that, the question about which demands a value is for, and the card that
// starts the case. The agent chooses the questions in code; the person's choice of scope is never assumed.

const forText = (items, L) => items.length <= 2 ? 'for ' + items.join(' and ') : `for ${items.length} ${L.plural}`

// Which demands an answer is for: all of them unless the person unticks some.
function useScope(items) {
  const [picked, setPicked] = useState(() => new Set(items))
  const toggle = (id) => setPicked(p => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const chosen = items.filter(i => picked.has(i))
  return { picked, toggle, chosen, scope: chosen.length === items.length ? 'all' : chosen, none: chosen.length === 0 }
}

function Scope({ items, s }) {
  if (items.length < 2) return null
  return (
    <div className="rc-scope"><span>Applies to:</span>
      {items.map(i => <label key={i}><input type="checkbox" checked={s.picked.has(i)} onChange={() => s.toggle(i)} />{i}</label>)}
    </div>)
}

const BLANK = { value: '', ask: false, picked: null }     // picked: null means all of the demands the question is open for

// The open questions as pages: each has its own answer box (or buttons for a pick list), drafts are kept while the person swipes
// between them, and one button sends everything answered. A question left alone stays open.
export function AnswerSheet({ qs, L, busy, onSend, at, setAt }) {
  const [drafts, setDrafts] = useState({})              // field -> { value, ask, picked }
  const box = useRef(null)
  const i = Math.min(at, qs.length - 1)
  const q = qs[i]
  const get = (f) => drafts[f] || BLANK
  const put = (f, patch) => setDrafts(s => ({ ...s, [f]: { ...(s[f] || BLANK), ...patch } }))
  const picked = (x) => { const d = get(x.field); return d.picked === null ? x.items : x.items.filter(id => d.picked.includes(id)) }
  const state = (x) => { const d = get(x.field); return !picked(x).length ? 'open' : d.ask ? 'asked' : d.value.trim() ? 'answered' : 'open' }
  const ready = qs.filter(x => state(x) !== 'open')
  const d = get(q.field)
  const mine = picked(q)

  useEffect(() => { if (box.current) box.current.focus() }, [i, q.field])      // the page you land on is ready to type in

  const go = (n) => setAt(Math.max(0, Math.min(qs.length - 1, n)))
  const send = () => {
    if (!ready.length || busy) return
    const answers = ready.map(x => {
      const ids = picked(x)
      const scope = ids.length === x.items.length ? 'all' : ids
      return get(x.field).ask ? { field: x.field, decline: true, scope } : { field: x.field, value: get(x.field).value.trim(), scope }
    })
    onSend(answers, ready.map(x => `${x.label}: ${get(x.field).ask ? 'Ask the requester' : get(x.field).value.trim()}`).join('\n'))
  }
  const toggleId = (id) => { const now = d.picked === null ? q.items : d.picked; put(q.field, { picked: now.includes(id) ? now.filter(x => x !== id) : [...now, id] }) }

  return (
    <div className="rc-q" role="group" aria-label="Open questions">
      <div className="rc-qnav">
        <span className="cs-faint">{qs.length > 1 ? `Question ${i + 1} of ${qs.length}` : 'Question'}{ready.length ? ` · ${ready.length} ready` : ''}</span>
        <span className="sp" />
        {qs.length > 1 && <button className="cs-link" disabled={i === 0} onClick={() => go(i - 1)} aria-label="Previous question">‹ Back</button>}
        {qs.length > 1 && <button className="cs-link" disabled={i === qs.length - 1} onClick={() => go(i + 1)} aria-label="Next question">Next ›</button>}
      </div>
      {qs.length > 1 && (
        <div className="rc-dots" role="tablist" aria-label="Questions">
          {qs.map((x, n) => <button key={x.field} role="tab" aria-selected={n === i} className={'rc-dot ' + state(x) + (n === i ? ' on' : '')}
            aria-label={`Question ${n + 1}: ${x.label}, ${state(x) === 'open' ? 'not answered' : state(x) === 'asked' ? 'ask the requester' : 'answered'}`} onClick={() => go(n)} />)}
        </div>)}
      <div className="rc-slide">
        <div className="rc-qh"><b>{q.label}</b><span className="cs-faint">{forText(q.items, L)}</span></div>
        {q.description && <div className="rc-help">{q.description}</div>}
        {q.items.length > 1 && (
          <div className="rc-scope"><span>Applies to:</span>
            {q.items.map(id => <label key={id}><input type="checkbox" checked={mine.includes(id)} onChange={() => toggleId(id)} />{id}</label>)}
          </div>)}
        {q.options.length > 0
          ? <div className="rc-opts">{q.options.map(o => (
            <button key={o} className={'btn sm' + (d.value === o && !d.ask ? ' primary' : '')} aria-pressed={d.value === o && !d.ask} disabled={busy}
              onClick={() => { put(q.field, { value: d.value === o ? '' : o, ask: false }); if (d.value !== o) go(i + 1) }}>{o}</button>))}</div>
          : <textarea ref={box} className="rq-in rc-ans" rows={2} aria-label={q.label} placeholder="Type the answer" value={d.ask ? '' : d.value} disabled={busy}
            onChange={e => put(q.field, { value: e.target.value, ask: false })}
            onKeyDown={e => {
              if (e.key !== 'Enter' || e.shiftKey) return
              e.preventDefault()
              if (e.metaKey || e.ctrlKey || i === qs.length - 1) send(); else go(i + 1)
            }} />}
        <div className="rc-opts">
          <button className={'btn sm' + (d.ask ? ' primary' : '')} aria-pressed={d.ask} disabled={busy || !mine.length}
            onClick={() => { put(q.field, { ask: !d.ask, value: '' }); if (!d.ask) go(i + 1) }}>Ask the requester</button>
          <span className="sp" />
          <span className="cs-faint" style={{ fontSize: 12.5 }}>{q.options.length ? 'Pick one, or skip it.' : 'Enter for the next question.'} Skipped ones stay open.</span>
        </div>
      </div>
      <div className="rc-opts">
        <button className="btn primary" disabled={busy || !ready.length} onClick={send}>{ready.length ? `Send ${ready.length} answer${ready.length === 1 ? '' : 's'}` : 'Send answers'}</button>
        {ready.length > 0 && ready.length < qs.length && <span className="cs-faint" style={{ fontSize: 12.5 }}>{qs.length - ready.length} will stay open.</span>}
      </div>
    </div>)
}

// Too many open questions to swipe through at first: name them, and offer the other ways to go on.
export function Gaps({ qs, L, busy, onOne, onAttach, onDeclineAll }) {
  return (
    <div className="rc-q" role="group" aria-label="Open questions">
      <div className="rc-qnav"><b>{qs.length} required details are missing</b></div>
      <ul className="rc-gaplist">{qs.map(q => <li key={q.field}><span>{q.label}</span><span className="cs-faint">{forText(q.items, L)}</span></li>)}</ul>
      <div className="rc-opts">
        <button className="btn sm" disabled={busy} onClick={onOne}>Go through them one by one</button>
        <button className="btn sm" disabled={busy} onClick={onAttach}>Attach a file</button>
        <button className="btn sm" disabled={busy} onClick={onDeclineAll}>Ask the requesters for all of these</button>
      </div>
      <div className="cs-faint" style={{ fontSize: 12.5 }}>Or write everything you know in the box below, in your own words.</div>
    </div>)
}

// A value was given without saying which demands it is for: the person says.
export function ScopeQuestion({ q, busy, onAnswer }) {
  const s = useScope(q.items)
  return (
    <div className="rc-q" role="group" aria-label="Which ones">
      <div className="rc-qnav"><b>Which one{q.items.length > 1 ? 's' : ''} is it for?</b></div>
      <Scope items={q.items} s={s} />
      <div className="rc-opts">
        <button className="btn sm primary" disabled={busy || s.none} onClick={() => onAnswer({ scope: s.scope }, s.scope === 'all' ? `All ${q.items.length}` : `Only the ${s.chosen.length} chosen`)}>
          {s.scope === 'all' ? `All ${q.items.length}` : `Only the ${s.chosen.length} chosen`}</button>
      </div>
    </div>)
}

// Nothing is left to ask: start the case. A demand that is still incomplete is held and returned for information.
export function Ready({ req, busy, onStart, gapsUrl }) {
  const s = req.summary
  const L = req.item_label
  const many = (n) => `${n} ${n === 1 ? L.singular : L.plural}`
  if (s.problems > 0) return <div className="rc-q"><div className="cs-need">Two {L.plural} cannot share an ID. Fix the sheet and attach it again, or start over.</div></div>
  return (
    <div className="rc-q rc-ready" role="group" aria-label="Start the case">
      <div><b>{req.ready ? (s.total === 1 ? `The ${L.singular} is complete.` : `All ${many(s.total)} are complete.`) : `${s.complete} complete, ${s.incomplete} held for information.`}</b>
        <span className="cs-faint"> {req.ready ? 'Nothing is missing.' : `A held ${L.singular} is returned to its requester while the others carry on.`}</span></div>
      <div className="rc-opts">
        {req.ready
          ? <button className="btn primary" disabled={busy} onClick={() => onStart(false)}>Start the case</button>
          : <button className="btn primary" disabled={busy} onClick={() => onStart(true)}>Start anyway, holding {many(s.incomplete)}</button>}
        {!req.ready && <a className="btn" href={gapsUrl}>Download the gaps sheet</a>}
      </div>
    </div>)
}
