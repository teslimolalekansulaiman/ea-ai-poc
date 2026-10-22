import { useEffect, useState } from 'react'
import { api } from '../api'

export default function Coverage() {
  const [d, setD] = useState(null)
  useEffect(() => { api.coverage().then(setD) }, [])
  if (!d) return <div className="wrap"><div className="empty">Loading…</div></div>
  const stats = [[d.nodes, 'Entities'], [d.edges, 'Relationships'], [d.communities, 'Communities'], [d.isolated_nodes, 'Edgeless nodes']]
  return (
    <div className="wrap">
      <div className="view-head"><div>
        <div className="eyebrow">Coverage &amp; completeness</div>
        <h1>What the graph contains</h1>
        <p>Computed from the extracted graph — not opinion.</p>
      </div></div>
      <div className="stat-grid">{stats.map(([n, l]) => (
        <div className="card stat" key={l}><div className="n">{n}</div><div className="l">{l}</div></div>
      ))}</div>
      <div className="cov-section card" style={{ padding: 16 }}>
        <h3>Entities by document kind</h3>
        <div className="tbl-scroll"><table className="data"><tbody>
          {Object.entries(d.by_kind).map(([k, v]) => <tr key={k}><td style={{ fontWeight: 600 }}>{k}</td><td style={{ textAlign: 'right' }}>{v}</td></tr>)}
        </tbody></table></div>
      </div>
      {d.isolated?.length > 0 && (
        <div className="cov-section card" style={{ padding: 16 }}>
          <h3><span className="dot" style={{ background: 'var(--warn)' }} />Edgeless entities ({d.isolated.length}) — kept, flagged for review</h3>
          <div className="tbl-scroll"><table className="data"><tbody>
            {d.isolated.map((n, i) => <tr key={i}><td style={{ fontWeight: 600 }}>{n.name}</td><td style={{ textAlign: 'right' }}><span className="pill neutral">{n.type}</span></td></tr>)}
          </tbody></table></div>
        </div>
      )}
    </div>
  )
}
