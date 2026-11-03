import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { RequestPanel } from './RequestPanel'

// The front of a case: say what is needed, or attach what it came in, and the agent fills in what it says and asks only for
// what is missing. The request lives on the server and the page address names it (?request=...), so a reload or a link
// continues the same conversation. Starting hands the demands to the engine, and the case screen takes over.

const SHEET = /\.(csv|xlsx|xlsm)$/i
const ACCEPT = '.csv,.xlsx,.xlsm,.txt,.md,.eml,.docx,.pptx,.pdf'

const Clip = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m21 11-9 9a5 5 0 0 1-7-7l9-9a3.5 3.5 0 0 1 5 5l-9 9a2 2 0 0 1-3-3l8-8" /></svg>
)

function Message({ m }) {
  return m.role === 'user'
    ? <div className="cs-msg u"><div className="cs-bubble">{m.text}</div></div>
    : <div className="cs-msg"><div className="cs-av">AA</div><div className="rc-agent">{m.text}</div></div>
}

// The open question: its answers as buttons, and which demands the answer is for (the person's choice, never assumed).
function Question({ q, busy, onAnswer }) {
  const [picked, setPicked] = useState(() => new Set(q.items))
  const toggle = (id) => setPicked(p => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const chosen = q.items.filter(i => picked.has(i))
  const scope = chosen.length === q.items.length ? 'all' : chosen
  const none = chosen.length === 0
  return (
    <div className="rc-q">
      {q.items.length > 1 && (
        <div className="rc-scope"><span>Applies to:</span>
          {q.items.map(i => <label key={i}><input type="checkbox" checked={picked.has(i)} onChange={() => toggle(i)} />{i}</label>)}
        </div>)}
      <div className="rc-opts">
        {q.kind === 'scope'
          ? <button className="btn sm primary" disabled={busy || none} onClick={() => onAnswer({ scope })}>{scope === 'all' ? `All ${q.items.length}` : `Only the ${chosen.length} chosen`}</button>
          : q.options.map(o => <button key={o.value} className="btn sm" disabled={busy || none} onClick={() => onAnswer({ value: o.value, scope })}>{o.label}</button>)}
        {q.can_decline !== false && <button className="btn sm" disabled={busy || none} onClick={() => onAnswer({ decline: true, scope })}>Ask the requester{chosen.length > 1 ? 's' : ''}</button>}
      </div>
      {q.kind === 'ask' && q.options.length === 0 && <div className="cs-faint" style={{ fontSize: 12.5 }}>Type your answer below.</div>}
    </div>
  )
}

function Composer({ text, setText, files, setFiles, busy, onSend, placeholder, fileRef, hint }) {
  return (
    <>
      <textarea rows={1} value={text} disabled={busy} placeholder={placeholder} aria-label="Message"
        onChange={e => setText(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSend() } }} />
      <div className="cs-crow">
        <input ref={fileRef} type="file" multiple accept={ACCEPT} hidden onChange={e => { const picked = Array.from(e.target.files); e.target.value = ''; setFiles(f => [...f, ...picked]) }} />
        <button className="cs-icon" onClick={() => fileRef.current.click()} aria-label="Attach files" title="Attach an email, a Word or PowerPoint file, a PDF, a text file or a sheet"><Clip /></button>
        {files.map((f, i) => <span key={f.name + i} className="cs-file">{f.name}<button aria-label={'Remove ' + f.name} onClick={() => setFiles(fs => fs.filter((_, j) => j !== i))}>✕</button></span>)}
        <span className="cs-faint" style={{ fontSize: 12 }}>{hint}</span>
        <span className="sp" />
        <button className="btn primary" disabled={busy || (!text.trim() && !files.length)} onClick={onSend}>{busy ? 'Reading…' : 'Send'}</button>
      </div>
    </>
  )
}

export function RequestIntake({ uc, L, beginCase }) {
  const nav = useNavigate()
  const [sp, setSp] = useSearchParams()
  const rid = sp.get('request')
  const [text, setText] = useState('')
  const [files, setFiles] = useState([])
  const [req, setReq] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [notice, setNotice] = useState('')           // what the agent said when it found nothing to start a request from
  const [sending, setSending] = useState(null)       // what the person just sent, shown while the agent reads it
  const fileRef = useRef(null)
  const scroller = useRef(null)
  const count = req ? req.messages.length : 0

  useEffect(() => {                                  // the address names the request: a reload or a link continues it
    if (!rid || (req && req.id === rid)) return undefined
    let live = true
    setBusy(true)
    api.requestGet(rid)
      .then(r => { if (!live) return; if (r.status === 'submitted') nav('/cases/' + r.case_id, { replace: true }); else setReq(r) })
      .catch(e => { if (live) { setErr(String(e.message || e)); setSp({}, { replace: true }) } })
      .finally(() => { if (live) setBusy(false) })
    return () => { live = false }
  }, [rid])                                          // eslint-disable-line

  useEffect(() => {                                  // the address no longer names a request (a new case was chosen): start clean
    if (!rid && req) { setReq(null); setFiles([]); setText(''); setErr(''); setNotice('') }
  }, [rid])                                          // eslint-disable-line

  useEffect(() => { const el = scroller.current; if (el) el.scrollTop = el.scrollHeight }, [count, sending, busy])

  const open = (r) => { setSp({ request: r.id }, { replace: true }); setReq(r); setText(''); setFiles([]) }
  const reset = () => { setReq(null); setFiles([]); setText(''); setErr(''); setNotice(''); setSp({}, { replace: true }) }
  const guard = async (fn) => { setErr(''); setBusy(true); try { await fn() } catch (e) { setErr(String(e.message || e)) } finally { setBusy(false) } }

  const start = () => guard(async () => {
    const t = text.trim()
    if (!t && !files.length) return
    setNotice('')
    const sheets = files.filter(f => SHEET.test(f.name))
    const others = files.filter(f => !SHEET.test(f.name))
    if (sheets.length > 1) throw new Error('Attach one sheet at a time.')
    if (sheets.length === 1) {                       // a sheet is one demand per row; anything else attached is read for its gaps
      let r = await api.requestFromFile(uc.id, sheets[0])
      if (t || others.length) r = (await api.requestSources(r.id, t, others)).request
      else if (r.ready) { const out = await api.requestSubmit(r.id, false); nav('/cases/' + out.case_id, { state: { unmatched: r.unmatched } }); return }
      else r = (await api.requestMessage(r.id, {})).request
      open(r)
      return
    }
    const out = await api.requestFromSources(uc.id, t, others)
    if (!out.request) { setNotice(out.reply); return }
    open(out.request)
  })

  const asIs = () => guard(async () => {              // the agent could not read it: start the old way, with the text as it is
    const r = await beginCase(uc.id, null, text)
    nav('/cases/' + r.id, { state: { unmatched: r.unmatched } })
  })

  const send = async () => {
    const t = text.trim()
    if (!t && !files.length) return
    const f = files
    setErr(''); setBusy(true); setSending(t || 'Attached: ' + f.map(x => x.name).join(', ')); setText(''); setFiles([])
    try { setReq((f.length ? await api.requestSources(req.id, t, f) : await api.requestMessage(req.id, { text: t })).request) }
    catch (e) { setErr(String(e.message || e)); setText(t); setFiles(f) }
    finally { setBusy(false); setSending(null) }
  }
  const answer = async (body) => {
    setErr(''); setBusy(true); setSending(body.decline ? 'Ask the requester' : (body.value || 'That one'))
    try { setReq((await api.requestMessage(req.id, { answer: body })).request) }
    catch (e) { setErr(String(e.message || e)) }
    finally { setBusy(false); setSending(null) }
  }
  const run = async (fn) => { setErr(''); setBusy(true); try { setReq(await fn()) } catch (e) { setErr(String(e.message || e)) } finally { setBusy(false) } }
  const go = (allow) => guard(async () => { const out = await api.requestSubmit(req.id, allow); nav('/cases/' + out.case_id, { state: { unmatched: req.unmatched } }) })

  if (req) {
    const q = req.pending && req.pending.items && req.pending.items.length ? req.pending : null
    return (
      <div className="rc">
        <section className="rc-chat" aria-label="Conversation with the request agent">
          <div className="rc-msgs" ref={scroller}>
            {req.messages.map((m, i) => <Message key={i} m={m} />)}
            {sending && <Message m={{ role: 'user', text: sending }} />}
            {busy && <div className="rc-working"><span className="cs-spin" />Reading…</div>}
            {!req.messages.length && !busy && <div className="cs-muted">Tell me what you know about the missing information, or attach a file that holds it.</div>}
          </div>
          {q && <Question key={q.kind + q.field + q.items.join(',')} q={q} busy={busy} onAnswer={answer} />}
          <div className="rc-comp">
            <Composer text={text} setText={setText} files={files} setFiles={setFiles} busy={busy} onSend={send} fileRef={fileRef}
              placeholder={q && q.options.length === 0 ? 'Type your answer, or attach a file…' : 'Write, or attach a file…'} hint="Enter to send" />
          </div>
        </section>
        <section className="rc-side">
          <RequestPanel req={req} busy={busy} run={run} onStart={go} onBack={reset} />
          {err && <div className="cs-need" style={{ marginTop: 10 }}>{err}</div>}
        </section>
      </div>
    )
  }

  return (
    <>
      <div className="cs-scroll"><div className="cs-col cs-empty">
        <div><div className="eyebrow">{uc.name}</div><h1 style={{ marginTop: 6 }}>Start a new case</h1></div>
        <p className="cs-muted" style={{ maxWidth: '60ch' }}>Describe the {L.singular}, paste it, or attach what it came in: an email, a Word or PowerPoint file, or a spreadsheet with one {L.singular} per row. I read it, fill in what it says, and ask only for what is missing before anything runs.</p>
        <div className="cs-how">
          <div><b>1. Say what is needed</b><span>Type it, paste it, or attach an email, a document, or a sheet of {L.plural}.</span></div>
          <div><b>2. Fill the gaps</b><span>I fill in what it says, with the words I took each value from, and ask only for what is missing.</span></div>
          <div><b>3. Start the case</b><span>Then the case runs: a quick check, the screening, and a recommendation for you to review.</span></div>
        </div>
        {notice && (
          <div className="rc-note">
            <div>{notice}</div>
            <div className="cs-actions"><button className="btn sm" disabled={busy || !text.trim()} onClick={asIs}>Start the case with my text as it is</button></div>
          </div>)}
        {err && <div className="cs-need">{err}</div>}
      </div></div>
      <div className="cs-composer-wrap"><div className="cs-composer">
        <Composer text={text} setText={setText} files={files} setFiles={setFiles} busy={busy} onSend={start} fileRef={fileRef}
          placeholder={`Type or paste a ${L.singular}, or attach an email, a document or a sheet of ${L.plural}...`} hint="Enter to send, Shift+Enter for a new line" />
      </div></div>
    </>
  )
}
