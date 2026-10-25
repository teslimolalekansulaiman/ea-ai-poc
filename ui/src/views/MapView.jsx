import { useEffect, useState, useMemo } from 'react'
import { api } from '../api'
import { Markdown } from '../cite'
import Graph from '../components/Graph'

const DOMV = { Motivation: '--l-strategy', Business: '--l-business', Data: '--l-application', Application: '--l-application', Technology: '--l-technology', Realization: '--l-security', Other: '--fg-muted' }
const cvar = (d) => `var(${DOMV[d] || '--fg-muted'})`

export default function MapView() {
  const [all, setAll] = useState({ nodes: [], edges: [] })
  const [comms, setComms] = useState([])
  const [sel, setSel] = useState(null)
  const [inspect, setInspect] = useState(null)
  const [lsPage, setLsPage] = useState(null)

  useEffect(() => { (async () => {
    setAll(await api.map())
    const d = await api.landscape()
    const cs = d.communities.slice().sort((a, b) => b.size - a.size)
    setComms(cs); setSel(cs[0]?.name || '__all')
  })() }, [])

  const nameOf = (id) => (all.nodes.find((n) => n.id === id)?.name) || id

  const { nodes, edges } = useMemo(() => {
    if (!sel) return { nodes: [], edges: [] }
    if (sel === '__all') return { nodes: all.nodes, edges: all.edges }
    const mem = new Set(all.nodes.filter((n) => n.community === sel).map((n) => n.id))
    const keep = new Set(mem)
    all.edges.forEach((e) => { if (mem.has(e.source)) keep.add(e.target); if (mem.has(e.target)) keep.add(e.source) })
    return {
      nodes: all.nodes.filter((n) => keep.has(n.id)).map((n) => ({ ...n, member: mem.has(n.id) ? 1 : 0 })),
      edges: all.edges.filter((e) => keep.has(e.source) && keep.has(e.target)),
    }
  }, [sel, all])

  function onNode(id) {
    const n = all.nodes.find((x) => x.id === id); if (!n) return
    setLsPage(null)
    setInspect({
      n,
      out: edges.filter((e) => e.source === id).map((e) => ({ r: e.relation, t: nameOf(e.target) })),
      inc: edges.filter((e) => e.target === id).map((e) => ({ r: e.relation, s: nameOf(e.source) })),
    })
  }
  async function openLs(slug) {
    setInspect(null); setLsPage({ loading: true })
    try { setLsPage(await api.landscapePage(slug)) } catch { setLsPage({ error: true }) }
  }

  return (
    <div className="wrap">
      <div className="view-head"><div>
        <div className="eyebrow">Visualize the landscape</div>
        <h1>Architecture map</h1>
        <p>One community at a time (with its direct neighbours, dimmed). Click a node to trace what it depends on and affects.</p>
      </div></div>
      <div className="ls-toolbar">
        <span style={{ fontSize: 12, color: 'var(--fg-faint)', marginRight: 4 }}>Community:</span>
        {comms.map((c) => (
          <button key={c.slug} className="lfilter" aria-pressed={sel === c.name} onClick={() => setSel(c.name)}>
            <span className="dot" style={{ background: cvar(c.domain) }} />{c.name} · {c.size}
          </button>
        ))}
        <button className="lfilter" aria-pressed={sel === '__all'} onClick={() => setSel('__all')}>All {all.nodes.length}</button>
      </div>
      <div className="ls-stage">
        <div className="graph-box"><Graph nodes={nodes} edges={edges} onNodeClick={onNode} /></div>
        <aside className="card inspect">
          {inspect ? (
            <>
              <h4>{inspect.n.name}</h4>
              <div className="sub"><span className="layer-tag" style={{ background: cvar(inspect.n.domain) }}>{inspect.n.domain}</span> <span className="pill neutral">{inspect.n.type}</span></div>
              <div className="ilist-label">Depends on / affects →</div>
              <div className="ilist">{inspect.out.length ? inspect.out.map((o, i) => <div key={i}><span className="mono" style={{ color: 'var(--fg-faint)', fontSize: 11 }}>{o.r}</span> {o.t}</div>) : <div className="empty">nothing outgoing</div>}</div>
              <div className="ilist-label">← Depended on by</div>
              <div className="ilist">{inspect.inc.length ? inspect.inc.map((o, i) => <div key={i}><span className="mono" style={{ color: 'var(--fg-faint)', fontSize: 11 }}>{o.r}</span> {o.s}</div>) : <div className="empty">nothing incoming</div>}</div>
            </>
          ) : lsPage ? (
            lsPage.loading ? <div className="empty">Loading…</div> : lsPage.error ? <div className="empty">No landscape page.</div> : <Markdown md={lsPage.markdown} />
          ) : (
            <>
              <div className="empty">Click a node to inspect it.</div>
              {comms.some((c) => c.has_page) && <div className="ilist-label" style={{ marginTop: 14 }}>Community landscape pages</div>}
              <div className="ilist">{comms.filter((c) => c.has_page).map((c) => (
                <div key={c.slug}><a href="#" onClick={(e) => { e.preventDefault(); openLs(c.slug) }}>{c.name}</a></div>
              ))}</div>
            </>
          )}
        </aside>
      </div>
    </div>
  )
}
