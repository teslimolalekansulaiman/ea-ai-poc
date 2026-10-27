import { createContext, useContext, useState, useCallback } from 'react'
import { api } from './api'
import { mdToHtml } from './lib/markdown'

const CiteCtx = createContext(null)
export const useCite = () => useContext(CiteCtx)

// Parse a markdown table ("| a | b |\n|---|---|\n| 1 | 2 |") into {header, rows}.
function parseMdTable(md) {
  const lines = (md || '').split(/\n/).map(l => l.trim()).filter(l => l.includes('|'))
  if (lines.length < 2) return null
  const cells = (l) => l.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map(s => s.trim())
  const isSep = (l) => /^[\s|:-]+$/.test(l)
  const header = cells(lines[0])
  const rows = lines.slice(1).filter(l => !isSep(l)).map(cells)
  return rows.length ? { header, rows } : null
}

export function CiteProvider({ children }) {
  const [block, setBlock] = useState(null)   // null = closed
  const open = useCallback(async (id) => {
    setBlock({ id, loading: true })
    try {
      if (id.startsWith('wiki:')) {           // a wiki page the case read (the entity's own page)
        const pg = await api.page(id.slice(5))
        setBlock({ id, block_id: id, doc_id: 'wiki', file: 'Wiki page', section: pg.title, kind: 'wiki', type: 'text', text: pg.markdown })
      } else setBlock({ id, ...(await api.block(id)) })
    }
    catch { setBlock({ id, error: true }) }
  }, [])
  const close = useCallback(() => setBlock(null), [])
  return (
    <CiteCtx.Provider value={{ open }}>
      {children}
      {block && (
        <div className="modal-bg open" onClick={(e) => { if (e.target === e.currentTarget) close() }}>
          <div className="modal" role="dialog" aria-modal="true">
            <div className="mh"><strong>Source block</strong><button className="x" onClick={close}>×</button></div>
            <div className="mb">
              {block.loading && <div className="empty">Loading…</div>}
              {block.error && <div className="empty">No source recorded for {block.id}.</div>}
              {!block.loading && !block.error && (
                <>
                  <div className="srcmeta">
                    <span className="pill neutral">{block.block_id}</span>
                    <span>{block.file || block.doc_id + '.docx'}</span><span>·</span><span>{block.section}</span>
                    <span className="pill info">{block.kind}</span>
                    {block.type === 'figure' && <span className="pill warn">figure</span>}
                    {block.type === 'table' && <span className="pill warn">table</span>}
                  </div>
                  {block.image_url && (
                    <img className="src-img" src={block.image_url} alt={'Figure ' + block.block_id}
                      onError={(e) => { e.currentTarget.style.display = 'none' }} />
                  )}
                  {block.type === 'figure' && block.description && (
                    <div className="src-desc"><span className="k">AI description</span>{block.description}</div>
                  )}
                  {block.type === 'table' && parseMdTable(block.text) ? (
                    (() => { const t = parseMdTable(block.text); return (
                      <div className="src-tablewrap"><table className="data src-table">
                        <thead><tr>{t.header.map((h, i) => <th key={i}>{h}</th>)}</tr></thead>
                        <tbody>{t.rows.map((r, ri) => <tr key={ri}>{t.header.map((_, ci) => <td key={ci}>{r[ci] || ''}</td>)}</tr>)}</tbody>
                      </table></div>) })()
                  ) : (block.text && block.text !== block.description &&
                    <div className={'block' + (block.type === 'table' ? ' mono' : '')}>{block.text}</div>)}
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </CiteCtx.Provider>
  )
}

// Renders markdown and routes .cite clicks to the modal.
export function Markdown({ md }) {
  const { open } = useCite()
  return (
    <div className="page-body" onClick={(e) => {
      const el = e.target.closest('.cite')
      if (el) open(el.dataset.cite)
    }} dangerouslySetInnerHTML={{ __html: mdToHtml(md || '') }} />
  )
}
