import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { Markdown, useCite } from '../cite'
import '../cases.css'
import { AskCard, FullTable, LiveCard, PhaseTrack, ResultCard, Workspace, show } from '../components/CasesParts'

const when = (t) => { try { return new Date(t * 1000).toLocaleString() } catch { return '' } }

// ---- the sheet as CSV, built in the browser from what is on screen ----------------------------
function csvFor(data, phase) {
  const q = (v) => '"' + String(v ?? '').replace(/"/g, '""') + '"'
  const cells = data.cells[phase.id] || {}
  const head = ['Demand', 'Title', ...phase.columns.map(c => c.name)]
  const lines = phase.summary.rows.map(r => [r.id, r.title, ...phase.columns.map(c => show((cells[r.id] || {})[c.name]?.value))].map(q).join(','))
  return [head.map(q).join(','), ...lines].join('\r\n')
}
function download(name, text) {
  const url = URL.createObjectURL(new Blob(['﻿' + text], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a'); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// ---- no case yet: attach a sheet or type one demand; Enter starts the run -------------------------
function Intake({ ucs }) {
  const [text, setText] = useState('')
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [recent, setRecent] = useState([])
  const nav = useNavigate()
  const fileRef = useRef(null)
  const uc = ucs.find(u => u.enabled !== false)                                            // chosen automatically; changed from the case card
  useEffect(() => { api.casesList().then(r => setRecent(r.cases || [])).catch(() => {}) }, [])

  const start = async () => {
    if (busy || !uc || (!file && !text.trim())) return
    setErr(''); setBusy(true)
    try {
      const r = file ? await api.caseParseFile(uc.id, file) : await api.caseParseText(uc.id, text)
      if (r.error) { setErr(r.error); setBusy(false); return }
      const name = file ? file.name.replace(/\.[^.]+$/, '') : (r.items[0]?._id || 'Demand')
      const c = await api.caseCreate({ use_case_id: uc.id, items: r.items, name })
      nav('/cases/' + c.id, { state: { unmatched: r.unmatched || [] } })
    } catch (e) { setErr(String(e.message || e)); setBusy(false) }
  }

  if (!uc) return <div className="cs-scroll"><div className="cs-col cs-empty"><h1>No use case yet</h1>
    <p className="cs-muted">Create one under <b>Config</b>, then come back to run demands through it.</p></div></div>

  return (
    <>
      <div className="cs-scroll"><div className="cs-col cs-empty">
        <div><div className="eyebrow">Use case</div>
          <h1>{uc.name}</h1>
          <p className="cs-muted" style={{ marginTop: 6 }}>{uc.description || 'Attach the demands to assess.'}</p></div>
        {err && <div className="cs-need">{err}</div>}
        {recent.length > 0 && (<div><div className="eyebrow" style={{ marginBottom: 6 }}>Recent cases</div>
          <div className="cs-recents">{recent.slice(0, 6).map(c => (
            <button key={c.id} onClick={() => nav('/cases/' + c.id)}><span>{c.name}</span><span className="cs-faint" style={{ fontSize: 12 }}>{when(c.created_at)}</span></button>))}</div></div>)}
      </div></div>

      <div className="cs-composer-wrap"><div className="cs-composer">
        {file && <span className="cs-file">{file.name}<button aria-label="Remove file" onClick={() => setFile(null)}>✕</button></span>}
        <textarea rows={2} value={text} disabled={busy} onChange={e => setText(e.target.value)}
          placeholder={file ? 'Press Enter to start with this sheet' : 'Type or paste a demand, or attach a sheet (CSV or Excel) with one demand per row'}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); start() } }} />
        <div className="cs-crow">
          <input ref={fileRef} type="file" accept=".csv,.xlsx,.xlsm" hidden onChange={e => { setFile(e.target.files[0] || null); e.target.value = '' }} />
          <button className="btn sm" onClick={() => fileRef.current.click()}>Attach sheet</button>
          <span className="cs-pill info">Using {uc.name}</span>
          <span className="sp" />
          <button className="btn primary sm" disabled={busy || (!file && !text.trim())} onClick={start}>{busy ? 'Starting…' : 'Start'}</button>
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
  const [wsOpen, setWsOpen] = useState(() => window.innerWidth >= 1500)
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
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [showAllQs, setShowAllQs] = useState(false)
  const seq = useRef(0)
  const burst = useRef(Date.now() + 15000)
  const scroller = useRef(null)

  const load = useCallback(async () => {
    try {
      const d = await api.caseGet(id, seq.current)
      seq.current = d.last_seq
      if (d.events.length) setEvents(e => [...e, ...d.events].slice(-200))
      setData(d)
    } catch (e) { setErr(String(e.message || e)) }
  }, [id])
  useEffect(() => { api.caseDocuments().then(r => setDocs(r.documents || [])).catch(() => {}) }, [])
  useEffect(() => { seq.current = 0; setEvents([]); setData(null); setThread([]); setViewed(null); load() }, [id, load])

  const running = !!data && data.phases.some(p => p.state.status === 'running')
  useEffect(() => {
    const t = setInterval(() => { if (running || Date.now() < burst.current) load() }, 2000)
    return () => clearInterval(t)
  }, [running, load])
  const poke = () => { burst.current = Date.now() + 20000; load() }

  // the phase on show: the one being worked, else the latest that has started
  const current = useMemo(() => {
    if (!data) return null
    const live = data.phases.find(p => p.state.status === 'running')
    const started = [...data.phases].reverse().find(p => p.state.status && p.state.status !== 'waiting')
    return (live || started || data.phases[0]).id
  }, [data])
  const phaseId = viewed || current
  const phase = data && data.phases.find(p => p.id === phaseId)
  const idx = data ? data.phases.findIndex(p => p.id === phaseId) : 0
  const next = data && data.phases[idx + 1]
  const titleOf = (iid) => { const r = phase?.summary.rows.find(x => x.id === iid); return r?.title }

  const openQs = (data?.questions || []).filter(x => x.status === 'open' && x.phase_id === phaseId)
  const started = phase && phase.state.status && phase.state.status !== 'waiting'
  const hasResult = phase && ['review', 'approved'].includes(phase.state.status) && phase.summary.rows.length > 0
  const shownQs = showAllQs ? openQs : openQs.slice(0, 3)

  useEffect(() => { const el = scroller.current; if (el) el.scrollTop = el.scrollHeight }, [thread.length, asking, openQs.length])

  const act = async (fn) => { setBusy(true); setErr(''); try { await fn() ; poke() } catch (e) { setErr(String(e.message || e)) } finally { setBusy(false) } }
  const ask = async (text) => {
    const question = (text ?? q).trim(); if (!question || asking) return
    setQ(''); setAsking(true)
    const history = thread.flatMap(m => m.role === 'user' ? [{ role: 'user', content: m.text }] : [{ role: 'assistant', content: m.text }])
    setThread(t => [...t, { role: 'user', text: question }])
    try {
      const r = await api.caseAsk(id, question, history)
      setThread(t => [...t, { role: 'bot', text: r.answer || '(no answer)', blocks: (r.citations || r.sources || []).map(c => c.block_id || c.id || c).filter(Boolean).slice(0, 6) }])
    } catch (e) { setThread(t => [...t, { role: 'bot', text: 'That did not work: ' + String(e.message || e) }]) } finally { setAsking(false) }
  }

  const openPop = () => { setPop(p => !p); if (!ucs.length) api.usecases().then(r => setUcs(r.usecases || [])).catch(() => {}) }
  const changeUc = (u) => act(async () => {
    setPop(false)
    await api.caseCancel(id)
    const r = await api.caseCreate({ use_case_id: u.id, items: data.items, name: data.case.name })
    await api.caseDelete(id)
    nav('/cases/' + r.id, { replace: true })
  })

  if (err && !data) return <div className="cs-scroll"><div className="cs-col"><div className="cs-need">{err}</div><button className="btn" onClick={() => nav('/cases')}>Back</button></div></div>
  if (!data || !phase) return <div className="cs-scroll"><div className="cs-col cs-muted">Loading…</div></div>

  const runningHere = phase.state.status === 'running'
  const stateLabel = runningHere ? 'working' : (phase.state.status || 'waiting')

  return (
    <div className="cs-root">
      <div className="cs-main">
        <div className="cs-bar">
          <div className="cs-top">
            <div className="ttl"><b>{data.case.name}</b><span>{data.case.use_case_name} · {data.items.length} demand{data.items.length === 1 ? '' : 's'}</span></div>
            <button className="btn sm" onClick={() => nav('/cases')}>New case</button>
            <button className="btn sm" onClick={() => setWsOpen(o => !o)} aria-expanded={wsOpen}>{wsOpen ? 'Hide workspace' : 'Workspace'}</button>
          </div>
          <PhaseTrack phases={data.phases} viewed={phaseId} onPick={setViewed} />
        </div>

        <div className="cs-scroll" ref={scroller}><div className="cs-col">
          <div className="cs-msg"><div className="cs-av">AA</div><div className="cs-body"><div className="cs-card">
            <div className="eyebrow">New case</div><h3>{data.case.name}</h3>
            <div className="cs-det">{data.items.length} demand{data.items.length === 1 ? '' : 's'} found · using <span className="cs-pill info">{data.case.use_case_name}</span> · {data.phases.length} phase{data.phases.length === 1 ? '' : 's'}
              <button className="cs-link" onClick={openPop}>Change</button>
              {pop && <div className="cs-pop" role="menu">{ucs.map(u => (
                <button key={u.id} disabled={u.id === data.case.use_case_id || u.enabled === false} onClick={() => changeUc(u)}>
                  <span>{u.name}</span><span className="cs-faint">{u.id === data.case.use_case_id ? 'selected' : u.enabled === false ? 'planned' : 'switch'}</span></button>))}
                {ucs.length === 0 && <span className="cs-faint" style={{ padding: '6px 10px' }}>Loading…</span>}</div>}</div>
            {unmatched.length > 0 && <p className="cs-muted" style={{ margin: '8px 0 0', fontSize: 13 }}>Columns not recognised and ignored: {unmatched.join(', ')}.</p>}
          </div></div></div>

          {!started && <div className="cs-card cs-muted">{phase.name} has not started. {idx > 0 ? `It begins when you approve ${data.phases[idx - 1].name}.` : ''}</div>}
          {runningHere && <div className="cs-msg"><div className="cs-av">AA</div><div className="cs-body" style={{ minWidth: 0 }}>
            <LiveCard phase={phase} events={events} data={data} waiting={false}
              onCancel={() => act(() => api.caseCancel(id))} /></div></div>}

          {shownQs.map(x => <AskCard key={x.id} q={x} title={titleOf(x.item_id)} docs={docs}
            onAnswer={(body) => act(() => api.caseAnswer(id, x.id, body))} />)}
          {openQs.length > shownQs.length && <div className="cs-msg"><div className="cs-av" style={{ visibility: 'hidden' }}>AA</div><div className="cs-body">
            <button className="btn sm" onClick={() => setShowAllQs(true)}>Show the other {openQs.length - shownQs.length} question{openQs.length - shownQs.length === 1 ? '' : 's'}</button></div></div>}

          {hasResult && <ResultCard phase={phase} next={next} busy={busy || runningHere}
            onApprove={() => act(async () => { await api.caseApprove(id, phase.id); if (next) setViewed(next.id) })}
            onOpenTable={() => setTable(true)} onCsv={() => download(`${data.case.name} - ${phase.name}.csv`, csvFor(data, phase))}
            onPickItem={(iid) => { setWsOpen(true); setTab('demands'); setOpenItem(iid); setOpenCol(null) }} />}

          {hasResult && !runningHere && phase.summary.suggested.length > 0 && thread.length === 0 &&
            <div className="cs-chips">{phase.summary.suggested.map(s => <button key={s} className="cs-chip" onClick={() => ask(s)}>{s}</button>)}</div>}

          {thread.map((m, i) => m.role === 'user'
            ? <div className="cs-msg u" key={i}><div className="cs-bubble">{m.text}</div></div>
            : <div className="cs-msg" key={i}><div className="cs-av">AA</div><div className="cs-body"><div className="cs-card cs-ans">
                <Markdown md={m.text} />
                {m.blocks?.length > 0 && <div className="cs-used">Used: {m.blocks.map(b => <button key={b} className="cs-cite" onClick={() => cite.open(b)}>{b}</button>)}</div>}
              </div></div></div>)}
          {asking && <div className="cs-msg"><div className="cs-av">AA</div><div className="cs-body cs-muted">Reading the results…</div></div>}
          {err && <div className="cs-need">{err}</div>}
        </div></div>

        <div className="cs-composer-wrap"><div className="cs-composer">
          <textarea rows={1} value={q} onChange={e => setQ(e.target.value)} placeholder={`Ask about ${data.case.name}`}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask() } }} />
          <div className="cs-crow"><span className="cs-pill info">Using {data.case.name} · {stateLabel}</span><span className="sp" />
            <button className="btn primary sm" disabled={!q.trim() || asking} onClick={() => ask()}>Ask</button></div>
        </div></div>
      </div>

      <div className={'cs-scrim' + (wsOpen ? ' on' : '')} onClick={() => setWsOpen(false)} />
      <aside className={'cs-work' + (wsOpen ? ' open' : '')}>
        <Workspace data={data} phase={phase} tab={tab} setTab={setTab} openItem={openItem} setOpenItem={setOpenItem}
          openCol={openCol} setOpenCol={setOpenCol} readiness={readiness} onClose={() => setWsOpen(false)}
          onReadiness={async () => { setReadiness('loading'); try { setReadiness(await api.readiness(data.case.use_case_id, { case_id: id })) } catch (e) { setReadiness({ error: String(e.message || e) }) } }} />
      </aside>

      {table && <FullTable data={data} phase={phase} onClose={() => setTable(false)}
        onCsv={() => download(`${data.case.name} - ${phase.name}.csv`, csvFor(data, phase))} />}
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
