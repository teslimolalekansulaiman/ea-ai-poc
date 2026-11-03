import { useState } from 'react'

// What the request agent puts in front of the person, inside the chat: the open questions, one at a time (or as a list when there
// are too many to step through), the question about which demands a value is for, and the card that starts the case. The agent
// chooses the questions in code; the person's choice of scope is never assumed.

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

// One open question as a card. A pick list answers by button; free text is typed in the message box below.
function Slide({ q, L, busy, onAnswer }) {
  const s = useScope(q.items)
  return (
    <div className="rc-slide">
      <div className="rc-qh"><b>{q.label}</b><span className="cs-faint">{forText(q.items, L)}</span></div>
      {q.description && <div className="rc-help">{q.description}</div>}
      <Scope items={q.items} s={s} />
      {q.options.length > 0 && (
        <div className="rc-opts">{q.options.map(o => <button key={o} className="btn sm" disabled={busy || s.none} onClick={() => onAnswer({ value: o, scope: s.scope, field: q.field }, o)}>{o}</button>)}</div>)}
      <div className="rc-opts">
        {q.options.length === 0 && <span className="cs-faint" style={{ fontSize: 12.5 }}>Type it below{q.items.length > 1 ? ' and say if it is only for some of them' : ''}.</span>}
        <span className="sp" />
        <button className="btn sm" disabled={busy || s.none} onClick={() => onAnswer({ decline: true, scope: s.scope, field: q.field }, 'Ask the requester')}>Ask the requester</button>
      </div>
    </div>)
}

// Open questions, one at a time, with the way to step between them.
export function Steps({ qs, i, setI, L, busy, onAnswer, onAll }) {
  const q = qs[Math.min(i, qs.length - 1)]
  const at = Math.min(i, qs.length - 1)
  return (
    <div className="rc-q" role="group" aria-label="Open question">
      <div className="rc-qnav">
        <span className="cs-faint">{qs.length > 1 ? `Question ${at + 1} of ${qs.length}` : 'Question'}</span>
        <span className="sp" />
        {qs.length > 1 && <button className="cs-link" disabled={at === 0} onClick={() => setI(at - 1)} aria-label="Previous question">‹ Back</button>}
        {qs.length > 1 && <button className="cs-link" disabled={at === qs.length - 1} onClick={() => setI(at + 1)} aria-label="Next question">Next ›</button>}
        {qs.length > 1 && <button className="cs-link" onClick={onAll}>Answer in one message instead</button>}
      </div>
      <Slide key={q.field + q.items.join(',')} q={q} L={L} busy={busy} onAnswer={onAnswer} />
    </div>)
}

// Too many open questions to step through: name them, and offer the other ways to go on.
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
      <div><b>{req.ready ? `All ${many(s.total)} are complete.` : `${s.complete} complete, ${s.incomplete} held for information.`}</b>
        <span className="cs-faint"> {req.ready ? 'Nothing is missing.' : `A held ${L.singular} is returned to its requester while the others carry on.`}</span></div>
      <div className="rc-opts">
        {req.ready
          ? <button className="btn primary" disabled={busy} onClick={() => onStart(false)}>Start the case</button>
          : <button className="btn primary" disabled={busy} onClick={() => onStart(true)}>Start anyway, holding {many(s.incomplete)}</button>}
        {!req.ready && <a className="btn" href={gapsUrl}>Download the gaps sheet</a>}
      </div>
    </div>)
}
