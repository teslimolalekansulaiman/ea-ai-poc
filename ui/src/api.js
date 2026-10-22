// One client for the FastAPI backend. Same-origin in production (FastAPI serves the
// built app); the Vite dev server proxies /api to the running service.
async function J(url, opts) {
  const r = await fetch(url, opts)
  if (!r.ok) {
    let detail = ''
    try { const j = await r.json(); detail = j.detail || '' } catch { /* non-json */ }
    throw new Error(detail || `${r.status} ${url}`)
  }
  return r.json()
}
const post = (url, body) =>
  J(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

export const api = {
  ask: (question) => post('/api/ask', { question }),
  pages: () => J('/api/pages'),
  page: (slug) => J('/api/pages/' + encodeURIComponent(slug)),
  landscape: () => J('/api/landscape'),
  landscapePage: (slug) => J('/api/landscape/' + encodeURIComponent(slug)),
  coverage: () => J('/api/coverage'),
  map: () => J('/api/map'),
  graph: (name) => J('/api/graph?name=' + encodeURIComponent(name)),
  kb: (q, k = 8) => J('/api/kb?q=' + encodeURIComponent(q) + '&k=' + k),
  docs: () => J('/api/docs'),
  block: (id) => J('/api/block/' + encodeURIComponent(id)),

  usecases: () => J('/api/usecases'),
  usecase: (id) => J('/api/usecases/' + encodeURIComponent(id)),
  createUsecase: (spec) => post('/api/usecases', spec),
  updateUsecase: (id, spec) => J('/api/usecases/' + encodeURIComponent(id),
    { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(spec) }),
  deleteUsecase: (id) => J('/api/usecases/' + encodeURIComponent(id), { method: 'DELETE' }),
}
