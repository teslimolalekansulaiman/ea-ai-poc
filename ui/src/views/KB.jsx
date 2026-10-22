import { useEffect, useState } from 'react'
import { api } from '../api'
import { useCite } from '../cite'

export default function KB() {
  const [docs, setDocs] = useState([])
  const [q, setQ] = useState('')
  const [res, setRes] = useState(null)
  const { open } = useCite()

  useEffect(() => { api.docs().then((d) => setDocs(d.docs)) }, [])
  useEffect(() => {
    const t = setTimeout(async () => {
      if (!q.trim()) { setRes(null); return }
      try { setRes(await api.kb(q, 8)) } catch { setRes({ results: [] }) }
    }, 350)
    return () => clearTimeout(t)
  }, [q])

  return (
    <div className="wrap">
      <div className="view-head"><div>
        <div className="eyebrow">Knowledge base</div>
        <h1>Foundational sources</h1>
        <p>The documents every answer is grounded in. Semantic search finds the exact blocks.</p>
      </div></div>
      <input className="search" placeholder="Search the knowledge base (semantic)…" value={q}
        onChange={(e) => setQ(e.target.value)}
        style={{ width: '100%', padding: '9px 12px', border: '1px solid var(--border)', borderRadius: 7, background: 'var(--surface)', color: 'var(--fg)', fontSize: 13, marginBottom: 14 }} />
      {res && (
        <div className="card" style={{ padding: 0, overflow: 'hidden', marginBottom: 20 }}>
          <div className="tbl-scroll"><table className="data">
            <thead><tr><th>Block</th><th>Section</th><th>Text</th></tr></thead>
            <tbody>{res.results.map((r, i) => (
              <tr key={i}>
                <td><span className="cite" onClick={() => open(r.block_id)}>{r.block_id}</span></td>
                <td style={{ whiteSpace: 'nowrap' }}>{r.section}</td>
                <td>{(r.text || '').slice(0, 110)}…</td>
              </tr>
            ))}</tbody>
          </table></div>
        </div>
      )}
      <div className="kb-grid">{docs.map((doc) => (
        <div className="card kb-doc" key={doc.doc_id}>
          <div className="top"><div className="fi" style={{ background: 'var(--l-application)' }}>DOCX</div>
            <div><div className="nm">{doc.doc_id}</div><div className="meta mono">{doc.doc_id}.docx</div></div></div>
          <div><span className="pill ok">✓ Parsed</span> <span className="pill neutral">{doc.kind}</span></div>
          <div className="stats"><span><b>{doc.blocks}</b> blocks</span></div>
        </div>
      ))}</div>
    </div>
  )
}
