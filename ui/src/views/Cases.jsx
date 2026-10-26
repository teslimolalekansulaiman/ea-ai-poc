import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { Markdown, useCite } from '../cite'
import '../cases.css'
import { AnsweredCard, AskCard, FinCard, FullTable, LiveCard, PhaseTrack, ResultCard, Workspace, count } from '../components/CasesParts'

// A sheet or a typed demand becomes a case: read it, create it, and the run starts at once.
async function beginCase(ucId, file, text) {
  const r = file ? await api.caseParseFile(ucId, file) : await api.caseParseText(ucId, text)
  if (r.error) throw new Error(r.error)
  const name = file ? file.name.replace(/\.[^.]+$/, '') : (r.items[0]?._id || 'Demand')
  const c = await api.caseCreate({ use_case_id: ucId, items: r.items, name })
  return { id: c.id, unmatched: r.unmatched || [] }
}

function download(url) { window.location.assign(url) }

// ---- no case yet: attach a sheet or type one demand; Enter starts the run -------------------------
function Intake({ ucs }) {
  const [text, setText] = useState('')
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const nav = useNavigate()
  const fileRef = useRef(null)
  const uc = ucs.find(u => u.enabled !== false)                // chosen automatically; changed from the case card
  const L = (uc && uc.input && uc.input.item_label) || { singular: 'item', plural: 'items' }

  const start = async () => {
    if (busy || !uc || (!file && !text.trim())) return
    setErr(''); setBusy(true)
    try {
      const r = await beginCase(uc.id, file, text)
      nav('/cases/' + r.id, { state: { unmatched: r.unmatched } })
    } catch (e) { setErr(String(e.message || e)); setBusy(false) }
  }

  if (!uc) return <div className="cs-scroll"><div className="cs-col cs-empty"><h1>No use case yet</h1>
    <p className="cs-muted">Create one under <b>Config</b>, then come back to run demands through it.</p></div></div>

  return (
    <>
      <div className="cs-scroll"><div className="cs-col cs-empty">
        <div><div className="eyebrow">{uc.name}</div><h1 style={{ marginTop: 6 }}>Start a new case</h1></div>
        <p className="cs-muted" style={{ maxWidth: '58ch' }}>Attach a spreadsheet, or enter a single {L.singular}. The agents apply the {uc.name} procedure to each {L.singular} and fill in the table. Questions you ask afterwards refer to this case until you start another.</p>
        <div className="cs-how">
          <div><b>1. Provide the input</b><span>A spreadsheet (Excel or CSV), or one {L.singular} entered here.</span></div>
          <div><b>2. Follow the progress</b><span>A live card shows what the agents are doing, how many {L.plural} they have reached, and where they need an answer from you.</span></div>
          <div><b>3. Review and ask</b><span>Why a {L.singular} got its result, which {L.plural} overlap, what to ask the requester.</span></div>
        </div>
        <div className="cs-actions"><button className="btn" onClick={() => fileRef.current.click()}>Attach a file</button></div>
        {err && <div className="cs-need">{err}</div>}
      </div></div>

      <div className="cs-composer-wrap"><div className="cs-composer">
        <textarea rows={1} value={text} disabled={busy} onChange={e => setText(e.target.value)}
          placeholder={file ? 'Press Enter to start with this sheet' : `Type or paste a ${L.singular}, or attach a sheet of ${L.plural}...`}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); start() } }} />
        <div className="cs-crow">
          <input ref={fileRef} type="file" accept=".csv,.xlsx,.xlsm" hidden onChange={e => { setFile(e.target.files[0] || null); e.target.value = '' }} />
          <button className="cs-icon" onClick={() => fileRef.current.click()} aria-label="Attach a demand sheet" title="Attach a demand sheet (.xlsx, .csv)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m21 11-9 9a5 5 0 0 1-7-7l9-9a3.5 3.5 0 0 1 5 5l-9 9a2 2 0 0 1-3-3l8-8" /></svg></button>
          {file && <span className="cs-file">{file.name}<button aria-label="Remove file" onClick={() => setFile(null)}>✕</button></span>}
          <span className="cs-faint" style={{ fontSize: 12 }}>Enter to send, Shift+Enter for a new line</span>
          <span className="sp" />
          <button className="btn primary" disabled={busy || (!file && !text.trim())} onClick={start}>{busy ? 'Starting…' : 'Send'}</button>
        </div></div></div>
    </>
  )
}

// ---- a case ----------------------------------------------------------------------------------------
function Case({ id }) {
  const nav = useNavigate()
  const cite = useCite()
  const [data, setData] = useState(null)
  const [events, setEvents] = useState([])
  const [viewed, setViewed] = useState(null)
  const [wsOpen, setWsOpen] = useState(() => window.innerWidth > 1100)
  const [docs, setDocs] = useState([])
  const [pop, setPop] = useState(false)
  const [ucs, setUcs] = useState([])
  const unmatched = useLocation().state?.unmatched || []
  const [tab, setTab] = useState('demands')
  const [openItem, setOpenItem] = useState(null)
  const [openCol, setOpenCol] = useState(null)
  const [table, setTable] = useState(false)
  const [readiness, setReadiness] = useState(null)
  const [thread, setThread] = useState([])
  const [q, setQ] = useState('')
  const [file, setFile] = useState(null)
  const [focus, setFocus] = useState(null)
  const [prompt, setPrompt] = useState(null)
  const [note, setNote] = useState('')
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [showAllQs, setShowAllQs] = useState(false)
  const seq = useRef(0)
  const burst = useRef(Date.now() + 15000)
  const scroller = useRef(null)
  const fileRef = useRef(null)

  const load = useCallback(async () => {
    try {
      const d = await api.caseGet(id, seq.current)
      seq.current = d.last_seq
      if (d.events.length) setEvents(e => [...e, ...d.events].slice(-200))
      setData(d)
    } catch (e) { setErr(String(e.message || e)) }
  }, [id])
  useEffect(() => { api.caseDocuments().then(r => setDocs(r.documents || [])).catch(() => {}); api.usecases().then(r => setUcs(r.usecases || [])).catch(() => {}) }, [])
  useEffect(() => { seq.current = 0; setEvents([]); setData(null); setThread([]); setViewed(null); setFocus(null); load() }, [id, load])

  const running = !!data && data.phases.some(p => p.state.status === 'running')
  useEffect(() => {
    const t = setInterval(() => { if (running || Date.now() < burst.current) load() }, 2000)
    return () => clearInterval(t)
  }, [running, load])
  const poke = () => { burst.current = Date.now() + 20000; load() }
  const say = (m) => { setNote(m); setTimeout(() => setNote(''), 2600) }

  // the phase on show: the one being worked, else the latest that has started
  const current = useMemo(() => {
    if (!data) return null
    const live = data.phases.find(p => p.state.status === 'running')
    const started = [...data.phases].reverse().find(p => p.state.status && p.state.status !== 'waiting')
    return (live || started || data.phases[0]).id
  }, [data])
  const phaseId = viewed || current
  const phase = data && data.phases.find(p => p.id === phaseId)
  const L = (data && data.item_label) || { singular: 'item', plural: 'items' }
  const idx = data ? data.phases.findIndex(p => p.id === phaseId) : 0
  const next = data && data.phases[idx + 1]
  const titleOf = (iid) => phase?.summary.rows.find(x => x.id === iid)?.title

  const phaseQs = (data?.questions || []).filter(x => x.phase_id === phaseId)
  const openQs = phaseQs.filter(x => x.status === 'open')
  const closedQs = phaseQs.filter(x => x.status !== 'open')
  const shownQs = showAllQs ? openQs : openQs.slice(0, 3)
  const status = phase?.state.status
  const started = phase && status && status !== 'waiting'
  const finished = phase && ['review', 'approved'].includes(status) && phase.summary.rows.length > 0

  useEffect(() => { const el = scroller.current; if (el) el.scrollTop = el.scrollHeight }, [thread.length, asking, openQs.length])

  const act = async (fn) => { setBusy(true); setErr(''); try { await fn(); poke() } catch (e) { setErr(String(e.message || e)) } finally { setBusy(false) } }
  const openActivity = () => { setTab('activity'); setWsOpen(true) }
  const jumpToQuestion = () => { const el = document.querySelector('.cs-ask:not(.done)'); if (el) el.scrollIntoView({ block: 'center', behavior: 'smooth' }) }
  const pickPhase = (p, kind, i) => {
    if (kind === 'locked') return say('Finish and approve the previous phase first, then this one starts.')
    if (kind === 'ready') { say(`Approved. Starting ${p.name}.`); return act(async () => { await api.caseApprove(id, data.phases[i - 1].id); setViewed(p.id) }) }
    setViewed(p.id)
  }
  const focusOn = (iid) => { setFocus(iid) }

  const ask = async (text) => {
    const question = (text ?? q).trim(); if (!question || asking) return
    setQ(''); setAsking(true)
    const history = thread.map(m => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.text }))
    setThread(t => [...t, { role: 'user', text: question }])
    try {
      const r = await api.caseAsk(id, question, history, focus)
      setThread(t => [...t, { role: 'bot', text: r.answer || '(no answer)', blocks: (r.citations || r.sources || []).map(c => c.block_id || c.id || c).filter(Boolean).slice(0, 6) }])
    } catch (e) { setThread(t => [...t, { role: 'bot', text: 'That did not work: ' + String(e.message || e) }]) } finally { setAsking(false) }
  }
  const send = () => {
    const text = q.trim()
    if (!text && !file) return
    if (file || text.length > 220) { setPrompt({ text, file }); return }
    ask(text)
  }
  const startNew = async () => {
    const p = prompt; setBusy(true)
    try { const r = await beginCase(data.case.use_case_id, p.file, p.text); setPrompt(null); setFile(null); setQ(''); nav('/cases/' + r.id, { state: { unmatched: r.unmatched } }) }
    catch (e) { say(String(e.message || e)) } finally { setBusy(false) }
  }

  const ucsOn = ucs.filter(u => u.enabled !== false)
  const changeUc = (u) => act(async () => {
    setPop(false)
    await api.caseCancel(id)
    const r = await api.caseCreate({ use_case_id: u.id, items: data.items, name: data.case.name })
    await api.caseDelete(id)
    nav('/cases/' + r.id, { replace: true })
  })

  if (err && !data) return <div className="cs-scroll"><div className="cs-col"><div className="cs-need">{err}</div><button className="btn" onClick={() => nav('/cases')}>Back</button></div></div>
  if (!data || !phase) return <div className="cs-scroll"><div className="cs-col cs-muted">Loading…</div></div>

  const runningHere = status === 'running'
  const exportXlsx = () => download(api.caseExportUrl(id, phase.id))

  return (
    <div className="cs-root">
      <div className="cs-main">
        <div className="cs-bar">
          <div className="cs-top">
            <div className="ttl"><b>{data.case.name}</b><span>{count(data.items.length, L)} · {data.case.use_case_name}</span></div>
            <button className="btn sm" onClick={() => setWsOpen(o => !o)} aria-expanded={wsOpen}>Workspace</button>
            <button className="btn sm" onClick={() => nav('/cases')}>Replace case</button>
          </div>
          <PhaseTrack phases={data.phases} viewed={phaseId} onPick={pickPhase} />
        </div>

        <div className="cs-scroll" ref={scroller}><div className="cs-col">
          <div className="cs-msg"><div className="cs-body"><div className="cs-card">
            <div className="eyebrow">New case</div><h3>{data.case.name}</h3>
            <div className="cs-det">{count(data.items.length, L)} found · using <span className="cs-pill user">{data.case.use_case_name}</span> · {data.phases.length} phase{data.phases.length === 1 ? '' : 's'}
              {ucsOn.length > 1 && <button className="cs-link" onClick={() => setPop(p => !p)}>Change</button>}
              {pop && <div className="cs-pop" role="menu">{ucsOn.map(u => (
                <button key={u.id} disabled={u.id === data.case.use_case_id} onClick={() => changeUc(u)}>
                  <span>{u.name}</span><span className="cs-faint">{u.id === data.case.use_case_id ? 'selected' : 'switch'}</span></button>))}</div>}</div>
            {unmatched.length > 0 && <p className="cs-muted" style={{ margin: '8px 0 0', fontSize: 13 }}>Columns not recognised and ignored: {unmatched.join(', ')}.</p>}
          </div></div></div>

          {!started && <div className="cs-card cs-muted">{phase.name} has not started. {idx > 0 ? `It begins when you approve ${data.phases[idx - 1].name}.` : ''}</div>}
          {runningHere && <LiveCard phase={phase} events={events} data={data} needs={openQs.length} onJump={jumpToQuestion} onActivity={openActivity} onCancel={() => act(() => api.caseCancel(id))} />}
          {finished && <FinCard phase={phase} n={phase.summary.rows.length} L={L} onActivity={openActivity} />}

          {closedQs.map(x => <AnsweredCard key={x.id} q={x} title={titleOf(x.item_id)} />)}
          {shownQs.map(x => <AskCard key={x.id} q={x} title={titleOf(x.item_id)} docs={docs}
            onAnswer={(body) => act(() => api.caseAnswer(id, x.id, body))} />)}
          {openQs.length > shownQs.length && <div className="cs-msg"><div className="cs-av" style={{ visibility: 'hidden' }}>AA</div><div className="cs-body">
            <button className="btn sm" onClick={() => setShowAllQs(true)}>Show the other {openQs.length - shownQs.length} question{openQs.length - shownQs.length === 1 ? '' : 's'}</button></div></div>}

          {finished && <ResultCard phase={phase} next={next} L={L} busy={busy || runningHere}
            onApprove={() => act(async () => { await api.caseApprove(id, phase.id); if (next) setViewed(next.id) })}
            onOpenTable={() => setTable(true)} onExport={exportXlsx}
            onPickItem={(iid) => { setWsOpen(true); setTab('demands'); setOpenItem(iid); setOpenCol(null); focusOn(iid) }} />}

          {finished && !runningHere && phase.summary.suggested.length > 0 && thread.length === 0 &&
            <div className="cs-msg"><div className="cs-av" style={{ visibility: 'hidden' }}>AA</div><div className="cs-body">
              <div className="cs-used" style={{ marginBottom: 6 }}>Ask about this case</div>
              <div className="cs-chips">{phase.summary.suggested.map(s => <button key={s} className="cs-chip" onClick={() => ask(s)}>{s}</button>)}</div></div></div>}

          {thread.map((m, i) => m.role === 'user'
            ? <div className="cs-msg u" key={i}><div className="cs-bubble">{m.text}</div></div>
            : <div className="cs-msg" key={i}><div className="cs-av">AA</div><div className="cs-body"><div className="cs-card cs-ans">
                <Markdown md={m.text} />
                {m.blocks?.length > 0 && <div className="cs-used">Used: {m.blocks.map(b => <button key={b} className="cs-cite" onClick={() => cite.open(b)}>{b}</button>)}</div>}
              </div></div></div>)}
          {asking && <div className="cs-msg"><div className="cs-av">AA</div><div className="cs-body cs-muted">Reading {data.case.name} and the knowledge base…</div></div>}
          {err && <div className="cs-need">{err}</div>}
        </div></div>

        <div className="cs-composer-wrap"><div className="cs-composer">
          {prompt && <div className="cs-newprompt">
            <span>{prompt.file ? 'You attached a file. Start a new case from it?' : `This looks like a new ${L.singular}. Start a new case?`}</span>
            <button className="btn sm primary" disabled={busy} onClick={startNew}>Start a new case</button>
            {!prompt.file && <button className="btn sm" onClick={() => { const t = prompt.text; setPrompt(null); ask(t) }}>Ask it as a question</button>}
            <button className="btn sm" onClick={() => setPrompt(null)}>Cancel</button></div>}
          <div className="cs-ctx">
            <span className="cs-pill user">Asking about {data.case.name}<button aria-label="Leave this case" onClick={() => nav('/cases')}>✕</button></span>
            {focus ? <span className="cs-pill soft">Focus: {focus}<button aria-label="Clear focus" onClick={() => setFocus(null)}>✕</button></span>
              : <span className="cs-faint" style={{ fontSize: 12 }}>All demands in this case. Open a demand to focus on it.</span>}
          </div>
          <textarea rows={1} value={q} onChange={e => setQ(e.target.value)}
            placeholder={focus ? `Ask about ${focus}...` : 'Ask about this case, or attach a new sheet to start another...'}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }} />
          <div className="cs-crow">
            <input ref={fileRef} type="file" accept=".csv,.xlsx,.xlsm" hidden onChange={e => { setFile(e.target.files[0] || null); e.target.value = '' }} />
            <button className="cs-icon" onClick={() => fileRef.current.click()} aria-label="Attach a demand sheet" title="Attach a demand sheet (.xlsx, .csv)">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m21 11-9 9a5 5 0 0 1-7-7l9-9a3.5 3.5 0 0 1 5 5l-9 9a2 2 0 0 1-3-3l8-8" /></svg></button>
            {file && <span className="cs-file">{file.name}<button aria-label="Remove file" onClick={() => setFile(null)}>✕</button></span>}
            <span className="cs-faint" style={{ fontSize: 12 }}>Enter to send, Shift+Enter for a new line</span>
            <span className="sp" />
            <button className="btn primary" disabled={(!q.trim() && !file) || asking} onClick={send}>Send</button>
          </div>
        </div></div>
      </div>

      <div className={'cs-scrim' + (wsOpen ? ' on' : '')} onClick={() => setWsOpen(false)} />
      <aside className={'cs-work' + (wsOpen ? ' open' : '')}>
        <Workspace data={data} phase={phase} docs={docs} L={L} tab={tab} setTab={setTab} openItem={openItem}
          setOpenItem={(iid) => { setOpenItem(iid); if (iid) focusOn(iid) }}
          openCol={openCol} setOpenCol={setOpenCol} readiness={readiness} onClose={() => setWsOpen(false)}
          onTable={() => { setTable(true); setWsOpen(false) }}
          onReadiness={async () => { setReadiness('loading'); try { setReadiness(await api.readiness(data.case.use_case_id, { case_id: id })) } catch (e) { setReadiness({ error: String(e.message || e) }) } }} />
      </aside>

      {table && <FullTable data={data} phase={phase} L={L} onPhase={setViewed} onClose={() => setTable(false)} onExport={exportXlsx} />}
      {note && <div className="cs-toast on" role="status">{note}</div>}
    </div>
  )
}

export default function Cases() {
  const { id } = useParams()
  const [ucs, setUcs] = useState([])
  useEffect(() => { api.usecases().then(r => setUcs(r.usecases || [])).catch(() => {}) }, [])
  return <div style={{ height: '100%', minHeight: 0 }}>
    {id ? <Case key={id} id={id} /> : <div className="cs-root"><div className="cs-main"><Intake ucs={ucs} /></div></div>}
  </div>
}
