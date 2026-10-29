// One client for the FastAPI backend. Same-origin in production (FastAPI serves the
// built app); the Vite dev server proxies /api to the running service.
async function J(url, opts) {
  const r = await fetch(url, opts)
  if (!r.ok) {
    let detail = ''
    try { const j = await r.json(); detail = j.detail || '' } catch { /* non-json */ }
    if (!detail && (r.status === 401 || r.status === 403)) {       // not the app (it always answers with a detail): the layer in front of it
      throw new Error(`The service refused the request (${r.status} ${url}). If you reach it through 'gcloud run services proxy', its login lasts about an hour: restart the proxy and reload this page. Files already uploaded are kept.`)
    }
    throw new Error(detail || `${r.status} ${url}`)
  }
  return r.json()
}
const post = (url, body) =>
  J(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

export const api = {
  ask: (question, history, deep) => post('/api/ask', { question, history, deep: !!deep }),
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
  uploadDoc: (file, kind) => { const fd = new FormData(); fd.append('file', file); fd.append('kind', kind || 'architecture'); return J('/api/docs/upload', { method: 'POST', body: fd }) },
  applyDocs: (remove, added, allowEmpty) => J('/api/docs/apply', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ remove, added, allow_empty: !!allowEmpty }) }),
  removeDoc: (docId) => J('/api/docs/' + encodeURIComponent(docId), { method: 'DELETE' }),
  block: (id) => J('/api/block/' + encodeURIComponent(id)),

  usecases: () => J('/api/usecases'),
  usecase: (id) => J('/api/usecases/' + encodeURIComponent(id)),
  createUsecase: (spec) => post('/api/usecases', spec),
  updateUsecase: (id, spec) => J('/api/usecases/' + encodeURIComponent(id),
    { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(spec) }),
  usecaseVersions: (id) => J('/api/usecases/' + encodeURIComponent(id) + '/versions'),
  restoreUsecase: (id, vid) => post('/api/usecases/' + encodeURIComponent(id) + '/restore', { vid }),
  usecaseFileDiff: (id) => J('/api/usecases/' + encodeURIComponent(id) + '/file-diff'),
  loadUsecaseFromFile: (id) => post('/api/usecases/' + encodeURIComponent(id) + '/load-from-file', {}),
  deleteUsecase: (id) => J('/api/usecases/' + encodeURIComponent(id), { method: 'DELETE' }),
  runUsecase: (id, body) => post('/api/usecases/' + encodeURIComponent(id) + '/run', body),

  metamodel: () => J('/api/metamodel'),
  relationCounts: () => J('/api/graph/relation-counts'),
  suggestRelations: (body) => J('/api/usecases/suggest-relations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
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
  caseRename: (id, name) => J('/api/cases/' + encodeURIComponent(id), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) }),
  caseDelete: (id) => J('/api/cases/' + encodeURIComponent(id), { method: 'DELETE' }),
  caseParseText: (use_case_id, text) => post('/api/cases/parse-text', { use_case_id, text }),
  caseParseFile: (ucId, file) => { const fd = new FormData(); fd.append('file', file); return J('/api/cases/parse-file?use_case_id=' + encodeURIComponent(ucId), { method: 'POST', body: fd }) },
  caseAnswer: (cid, qid, body) => post('/api/cases/' + encodeURIComponent(cid) + '/questions/' + encodeURIComponent(qid) + '/answer', body),
  caseDocuments: () => J('/api/cases/documents'),
  caseApprove: (cid, pid) => post('/api/cases/' + encodeURIComponent(cid) + '/phases/' + encodeURIComponent(pid) + '/approve', {}),
  caseResume: (cid, pid) => post('/api/cases/' + encodeURIComponent(cid) + '/phases/' + encodeURIComponent(pid) + '/resume', {}),
  caseCancel: (cid) => post('/api/cases/' + encodeURIComponent(cid) + '/cancel', {}),
  caseAsk: (cid, question, history, focus) => post('/api/cases/' + encodeURIComponent(cid) + '/ask', { question, history, focus }),
  caseExportUrl: (cid, phase) => '/api/cases/' + encodeURIComponent(cid) + '/export?phase=' + encodeURIComponent(phase || ''),
  readiness: (ucId, body) => post('/api/usecases/' + encodeURIComponent(ucId) + '/readiness', body),

  // history (chats + runs)
  chatsList: () => J('/api/chats'),
  chatGet: (id) => J('/api/chats/' + encodeURIComponent(id)),
  chatSave: (body) => post('/api/chats', body),
  chatDelete: (id) => J('/api/chats/' + encodeURIComponent(id), { method: 'DELETE' }),
  runsList: (useCase) => J('/api/runs' + (useCase ? '?use_case=' + encodeURIComponent(useCase) : '')),
  runGet: (id) => J('/api/runs/' + encodeURIComponent(id)),
}
