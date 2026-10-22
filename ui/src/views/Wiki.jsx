import { useEffect, useState } from 'react'
import { api } from '../api'
import { Markdown, useCite } from '../cite'

export default function Wiki() {
  const [pages, setPages] = useState([])
  const [q, setQ] = useState('')
  const [cur, setCur] = useState(null)
  const [page, setPage] = useState(null)
  const [rail, setRail] = useState(null)
  const { open } = useCite()

  useEffect(() => { api.pages().then((d) => { setPages(d.pages); if (d.pages[0]) load(d.pages[0].slug) }) }, [])

  async function load(slug) {
    setCur(slug); setPage(null); setRail(null)
    try {
      const d = await api.page(slug); setPage(d)
      try { setRail(await api.graph(d.title)) } catch { setRail({ out: [], in: [], blocks: [] }) }
    } catch { setPage({ title: slug, missing: true }) }
  }

  const shown = pages.filter((p) => p.title.toLowerCase().includes(q.toLowerCase()))
  const hasRel = rail && (rail.out.length || rail.in.length)

  return (
    <div className="wrap"><div className="wiki-grid">
      <aside className="wiki-nav">
        <input className="search" placeholder="Search subjects…" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="group">{shown.map((p) => (
          <button key={p.slug} aria-current={p.slug === cur} onClick={() => load(p.slug)}>{p.title}</button>
        ))}</div>
      </aside>
      <main>
        {!page ? <div className="empty">Loading…</div>
          : page.missing ? <div className="empty">No wiki page for this entity.</div>
          : <><div className="page-title">{page.title}</div><Markdown md={page.markdown} /></>}
      </main>
      <aside className="wiki-rail">
        {hasRel && (
          <div className="card rail-box"><h4>Relationships</h4>
            {rail.out.map((e, i) => <div className="rel" key={'o' + i}><span className="r">{e.relation} →</span><span className="t">{e.target}</span></div>)}
            {rail.in.map((e, i) => <div className="rel" key={'i' + i}><span className="r">← {e.relation}</span><span className="t">{e.source}</span></div>)}
          </div>
        )}
        {rail?.blocks?.length > 0 && (
          <div className="card rail-box"><h4>Source blocks</h4>
            <div>{rail.blocks.map((b) => <span key={b} className="cite" style={{ margin: '0 4px 4px 0', display: 'inline-block' }} onClick={() => open(b)}>{b}</span>)}</div>
          </div>
        )}
      </aside>
    </div></div>
  )
}
