import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { AnswerSheet, Gaps, Ready, ScopeQuestion } from './RequestAsk'
import { RequestSummary } from './RequestSummary'

// The front of a case: say what is needed, or attach what it came in, and the agent fills in what it says and asks only for
// what is missing. The request lives on the server and the page address names it (?request=...), so a reload or a link
// continues the same conversation. The whole exchange is in the chat: the agent says what it found, asks what is missing (one
// question at a time, or as a list when there are too many), and offers to start the case when nothing is left to ask. Starting
// hands the demands to the engine, and the case screen takes over.

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
  const [pre, setPre] = useState([])                // the conversation before any demand was found: what the person said, and what the agent answered
  const said = pre.filter(m => m.role === 'user' && m.said).map(m => m.text)       // the person's words so far, read together with the next message
  const [sending, setSending] = useState(null)       // what the person just sent, shown while the agent reads it
  const [at, setAt] = useState(0)                     // the page of the answer sheet being shown: what is typed in the message box answers that question
  const [sheet, setSheet] = useState(false)           // with too many open questions to swipe through at first, the person chose to go through them
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
    if (!rid && req) { setReq(null); setFiles([]); setText(''); setErr(''); setPre([]) }
  }, [rid])                                          // eslint-disable-line

  useEffect(() => { const el = scroller.current; if (el) el.scrollTop = el.scrollHeight }, [count, sending, busy, pre.length])

  const open = (r) => { setSp({ request: r.id }, { replace: true }); setReq(r); setText(''); setFiles([]); setSheet(false); setAt(0) }
  const reset = () => { setReq(null); setFiles([]); setText(''); setErr(''); setPre([]); setSheet(false); setAt(0); setSp({}, { replace: true }) }
  const guard = async (fn) => { setErr(''); setBusy(true); try { await fn() } catch (e) { setErr(String(e.message || e)) } finally { setBusy(false) } }

  const start = () => guard(async () => {
    const t = text.trim()
    if (!t && !files.length) return
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
    const heard = [...said, t].filter(Boolean).join('\n\n')             // what was said before counts: the next message adds to it
    setSending(t || 'Attached: ' + others.map(f => f.name).join(', '))
    try {
      const out = await api.requestFromSources(uc.id, heard, others)
      if (!out.request) {                              // nothing to start from yet: the exchange stays in the chat, and the next message adds to it
        setPre(p => [...p, { role: 'user', text: t || 'Attached: ' + others.map(f => f.name).join(', '), said: !!t }, { role: 'agent', text: out.reply }])
        setText('')
        return
      }
      open(out.request)
    } finally { setSending(null) }
  })

  const asIs = () => guard(async () => {              // the agent could not read it: start the old way, with the text as it is
    const r = await beginCase(uc.id, null, [...said, text.trim()].filter(Boolean).join('\n\n'))
    nav('/cases/' + r.id, { state: { unmatched: r.unmatched } })
  })

  // The message box answers the question on the page of the sheet that is showing, and reads anything else the person says too; with
  // the list showing (too many questions for the sheet) it is read against everything that is missing. Answers through the sheet's own
  // boxes go in one go.
  const ask = (r) => {
    const qs = r.questions || []
    const scopeQ = r.pending && r.pending.kind === 'scope' && r.pending.items && r.pending.items.length ? r.pending : null
    const showList = !scopeQ && qs.length > 0 && !r.stepwise && !sheet
    const showSheet = !scopeQ && qs.length > 0 && !showList
    return { qs, scopeQ, showList, showSheet, focus: showSheet ? qs[Math.min(at, qs.length - 1)] : null }
  }
  const exchange = async (shown, call) => {
    setErr(''); setBusy(true); setSending(shown)
    try { setReq((await call()).request); return true }
    catch (e) { setErr(String(e.message || e)); return false }
    finally { setBusy(false); setSending(null) }
  }
  const send = async () => {
    const t = text.trim()
    if (!t && !files.length) return
    const f = files
    const a = ask(req)
    const wide = f.length > 0 || (!a.scopeQ && a.qs.length > 0 && !a.focus)
    setText(''); setFiles([])
    const ok = await exchange(t || 'Attached: ' + f.map(x => x.name).join(', '),
      () => wide ? api.requestSources(req.id, t, f) : api.requestMessage(req.id, a.focus ? { text: t, field: a.focus.field } : { text: t }))
    if (!ok) { setText(t); setFiles(f) }
  }
  const answer = (body, shown) => {                      // a button: the question it is for travels beside it
    const { field, ...rest } = body
    return exchange(shown, () => api.requestMessage(req.id, field ? { answer: rest, field } : { answer: rest }))
  }
  const sendSheet = (answers, shown) => exchange(shown, () => api.requestMessage(req.id, { answers }))      // every answer in the sheet, once
  const saveValue = async (itemId, name, value) => {    // the person corrects a value in the summary
    setErr(''); setBusy(true)
    try { setReq(await api.requestSet(req.id, itemId, { values: { [name]: value } })); return true }
    catch (e) { setErr(String(e.message || e)); return false }
    finally { setBusy(false) }
  }
  const go = (allow) => guard(async () => { const out = await api.requestSubmit(req.id, allow); nav('/cases/' + out.case_id, { state: { unmatched: req.unmatched } }) })

  if (req) {
    const a = ask(req)
    const L = req.item_label
    const { showList, showSheet } = a
    const hint = a.scopeQ ? 'Say which, or use the buttons…' : a.focus ? `Answer “${a.focus.label}”, or write anything else you know…` : a.qs.length ? 'Tell me everything you know about what is missing, or attach a file…' : 'Anything to add or correct?'
    return (
      <div className="rc">
        <section className="rc-chat" aria-label="Conversation with the request agent">
          <div className="rc-head"><span className="cs-faint">{req.name}</span><span className="sp" /><button className="cs-link" disabled={busy} onClick={reset}>Start over</button></div>
          <div className="rc-msgs" ref={scroller}>
            {req.messages.map((m, i) => <Message key={i} m={m} />)}
            {sending && <Message m={{ role: 'user', text: sending }} />}
            {busy && <div className="rc-working"><span className="cs-spin" />Reading…</div>}
            {!req.messages.length && !busy && <div className="cs-muted">Tell me what you know about the missing information, or attach a file that holds it.</div>}
            {err && <div className="cs-need">{err}</div>}
          </div>
          <RequestSummary req={req} busy={busy} onSave={saveValue} />
          {a.scopeQ && <ScopeQuestion key={a.scopeQ.field + a.scopeQ.items.join(',')} q={a.scopeQ} busy={busy} onAnswer={answer} />}
          {showSheet && <AnswerSheet qs={a.qs} L={L} busy={busy} onSend={sendSheet} at={at} setAt={setAt} />}
          {showList &&
            <Gaps qs={a.qs} L={L} busy={busy} onOne={() => { setSheet(true); setAt(0) }} onAttach={() => fileRef.current && fileRef.current.click()}
              onDeclineAll={() => answer({ decline_all: true }, 'Ask the requesters for all of these')} />}
          {!a.scopeQ && a.qs.length === 0 && req.items.length > 0 && <Ready req={req} busy={busy} onStart={go} gapsUrl={api.requestGapsUrl(req.id)} />}
          <div className="rc-comp">
            <Composer text={text} setText={setText} files={files} setFiles={setFiles} busy={busy} onSend={send} fileRef={fileRef}
              placeholder={hint} hint="Enter to send" />
          </div>
        </section>
      </div>
    )
  }

  if (pre.length) {                                    // nothing to start a request from yet: keep talking, in the same chat
    return (
      <div className="rc">
        <section className="rc-chat" aria-label="Conversation with the request agent">
          <div className="rc-head"><span className="cs-faint">{uc.name}</span><span className="sp" /><button className="cs-link" disabled={busy} onClick={reset}>Start over</button></div>
          <div className="rc-msgs" ref={scroller}>
            {pre.map((m, i) => <Message key={i} m={m} />)}
            {sending && <Message m={{ role: 'user', text: sending }} />}
            {busy && <div className="rc-working"><span className="cs-spin" />Reading…</div>}
            {err && <div className="cs-need">{err}</div>}
          </div>
          <div className="rc-q"><div className="rc-opts">
            <button className="btn sm" disabled={busy || !said.length && !text.trim()} onClick={asIs}>Start the case with my text as it is</button>
          </div></div>
          <div className="rc-comp">
            <Composer text={text} setText={setText} files={files} setFiles={setFiles} busy={busy} onSend={start} fileRef={fileRef}
              placeholder={`Say what is needed, who asks for it and why, or attach a file…`} hint="Enter to send" />
          </div>
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
        {err && <div className="cs-need">{err}</div>}
      </div></div>
      <div className="cs-composer-wrap"><div className="cs-composer">
        <Composer text={text} setText={setText} files={files} setFiles={setFiles} busy={busy} onSend={start} fileRef={fileRef}
          placeholder={`Type or paste a ${L.singular}, or attach an email, a document or a sheet of ${L.plural}...`} hint="Enter to send, Shift+Enter for a new line" />
      </div></div>
    </>
  )
}
