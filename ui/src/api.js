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
  ask: (question, history) => post('/api/ask', { question, history }),
  pages: () => J('/api/pages'),
  page: (slug) => J('/api/pages/' + encodeURIComponent(slug)),
  landscape: () => J('/api/landscape'),
  landscapePage: (slug) => J('/api/landscape/' + encodeURIComponent(slug)),
  coverage: () => J('/api/coverage'),
  map: () => J('/api/map'),
  graph: (name) => J('/api/graph?name=' + encodeURIComponent(name)),
  kb: (q, k = 8) => J('/api/kb?q=' + encodeURIComponent(q) + '&k=' + k),
  docs: () => J('/api/docs'),
  addDoc: (file) => { const fd = new FormData(); fd.append('file', file); return J('/api/docs/add', { method: 'POST', body: fd }) },
  removeDoc: (docId) => J('/api/docs/' + encodeURIComponent(docId), { method: 'DELETE' }),
  block: (id) => J('/api/block/' + encodeURIComponent(id)),

  usecases: () => J('/api/usecases'),
  usecase: (id) => J('/api/usecases/' + encodeURIComponent(id)),
  createUsecase: (spec) => post('/api/usecases', spec),
  updateUsecase: (id, spec) => J('/api/usecases/' + encodeURIComponent(id),
    { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(spec) }),
  deleteUsecase: (id) => J('/api/usecases/' + encodeURIComponent(id), { method: 'DELETE' }),
  runUsecase: (id, body) => post('/api/usecases/' + encodeURIComponent(id) + '/run', body),

  metamodel: () => J('/api/metamodel'),
  mmNode: (key, obj) => J('/api/metamodel/node/' + encodeURIComponent(key), { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(obj) }),
  mmNodeDel: (key) => J('/api/metamodel/node/' + encodeURIComponent(key), { method: 'DELETE' }),
  mmEdge: (key, obj) => J('/api/metamodel/edge/' + encodeURIComponent(key), { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(obj) }),
  mmEdgeDel: (key) => J('/api/metamodel/edge/' + encodeURIComponent(key), { method: 'DELETE' }),
  reingestRun: () => post('/api/reingest', {}),
  reingestStatus: () => J('/api/reingest/status'),

  // cases: a sheet of demands run through a use case
  casesList: () => J('/api/cases'),
  caseGet: (id, after = 0) => J('/api/cases/' + encodeURIComponent(id) + '?after=' + after),
  caseCreate: (body) => post('/api/cases', body),
  caseDelete: (id) => J('/api/cases/' + encodeURIComponent(id), { method: 'DELETE' }),
  caseParseText: (use_case_id, text) => post('/api/cases/parse-text', { use_case_id, text }),
  caseParseFile: (ucId, file) => { const fd = new FormData(); fd.append('file', file); return J('/api/cases/parse-file?use_case_id=' + encodeURIComponent(ucId), { method: 'POST', body: fd }) },
  caseAnswer: (cid, qid, answer) => post('/api/cases/' + encodeURIComponent(cid) + '/questions/' + encodeURIComponent(qid) + '/answer', { answer }),
  caseApprove: (cid, pid) => post('/api/cases/' + encodeURIComponent(cid) + '/phases/' + encodeURIComponent(pid) + '/approve', {}),
  caseCancel: (cid) => post('/api/cases/' + encodeURIComponent(cid) + '/cancel', {}),
  caseAsk: (cid, question, history) => post('/api/cases/' + encodeURIComponent(cid) + '/ask', { question, history }),
  readiness: (ucId, body) => post('/api/usecases/' + encodeURIComponent(ucId) + '/readiness', body),

  // history (chats + runs)
  chatsList: () => J('/api/chats'),
  chatGet: (id) => J('/api/chats/' + encodeURIComponent(id)),
  chatSave: (body) => post('/api/chats', body),
  chatDelete: (id) => J('/api/chats/' + encodeURIComponent(id), { method: 'DELETE' }),
  runsList: (useCase) => J('/api/runs' + (useCase ? '?use_case=' + encodeURIComponent(useCase) : '')),
  runGet: (id) => J('/api/runs/' + encodeURIComponent(id)),
}
