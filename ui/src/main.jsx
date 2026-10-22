import React from 'react'
import { createRoot } from 'react-dom/client'
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom'
import './styles.css'
import App from './App'
import { CiteProvider } from './cite'
import Ask from './views/Ask'
import Wiki from './views/Wiki'
import MapView from './views/MapView'
import Coverage from './views/Coverage'
import KB from './views/KB'
import UseCases from './views/UseCases'
import Run from './views/Run'
import Model from './views/Model'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <CiteProvider>
      <HashRouter>
        <Routes>
          <Route path="/" element={<App />}>
            <Route index element={<Navigate to="/ask" replace />} />
            <Route path="ask" element={<Ask />} />
            <Route path="wiki" element={<Wiki />} />
            <Route path="map" element={<MapView />} />
            <Route path="coverage" element={<Coverage />} />
            <Route path="kb" element={<KB />} />
            <Route path="usecases" element={<UseCases />} />
            <Route path="run" element={<Run />} />
            <Route path="run/:id" element={<Run />} />
            <Route path="model" element={<Model />} />
          </Route>
        </Routes>
      </HashRouter>
    </CiteProvider>
  </React.StrictMode>
)
