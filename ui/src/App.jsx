import { NavLink, Outlet } from 'react-router-dom'

const NAV = [
  ['ask', 'Ask', 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z'],
  ['wiki', 'Wiki', 'M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z'],
  ['map', 'Map', 'M5 6m-2.5 0M19 6m-2.5 0M12 18m-2.5 0M7 7l4 9M17 7l-4 9'],
  ['coverage', 'Coverage', 'M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11'],
  ['kb', 'Sources', 'M3 5v14a9 3 0 0 0 18 0V5M3 5a9 3 0 0 0 18 0M3 5a9 3 0 0 1 18 0M3 12a9 3 0 0 0 18 0'],
  ['run', 'Run', 'M5 3l14 9-14 9V3z'],
  ['usecases', 'Config', 'M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6'],
]

function toggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme')
  const next = cur === 'dark' ? 'light' : (cur === 'light' ? 'dark'
    : (matchMedia('(prefers-color-scheme: dark)').matches ? 'light' : 'dark'))
  document.documentElement.setAttribute('data-theme', next)
  try { localStorage.setItem('aa-theme', next) } catch {}
}
try { const t = localStorage.getItem('aa-theme'); if (t) document.documentElement.setAttribute('data-theme', t) } catch {}

export default function App() {
  return (
    <div className="app">
      <nav className="rail" aria-label="Primary">
        <div className="brand" title="Architecture Atlas">AA</div>
        {NAV.map(([to, label, d]) => (
          <NavLink key={to} to={'/' + to} className="navbtn" title={label}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d={d} /></svg>{label}
          </NavLink>
        ))}
        <div className="spacer" />
        <button className="iconbtn" onClick={toggleTheme} title="Toggle theme" aria-label="Toggle theme">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
        </button>
      </nav>
      <div className="view-area">
        <Outlet />
      </div>
    </div>
  )
}
