import { createContext, useContext, useState, useCallback } from 'react'
import { api } from './api'
import { mdToHtml } from './lib/markdown'

const CiteCtx = createContext(null)
export const useCite = () => useContext(CiteCtx)

export function CiteProvider({ children }) {
  const [block, setBlock] = useState(null)   // null = closed
  const open = useCallback(async (id) => {
    setBlock({ id, loading: true })
    try { setBlock({ id, ...(await api.block(id)) }) }
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
                    <span>{block.doc_id}.docx</span><span>·</span><span>{block.section}</span>
                    <span className="pill info">{block.kind}</span>
                  </div>
                  <div className={'block' + (block.type === 'table' ? ' mono' : '')}>{block.text}</div>
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
