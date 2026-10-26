import { NavLink, Outlet } from 'react-router-dom'
import { useState } from 'react'
import { useChats } from './chats'

const NAV = [
  ['ask', 'Ask', 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z'],
  ['wiki', 'Wiki', 'M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z'],
  ['map', 'Map', 'M14.106 5.553a2 2 0 0 0 1.788 0l3.659-1.83A1 1 0 0 1 21 4.619v12.764a1 1 0 0 1-.553.894l-4.553 2.277a2 2 0 0 1-1.788 0l-4.212-2.106a2 2 0 0 0-1.788 0l-3.659 1.83A1 1 0 0 1 3 19.381V6.618a1 1 0 0 1 .553-.894l4.553-2.277a2 2 0 0 1 1.788 0zM15 5.764v15M9 3.236v15'],
  ['coverage', 'Coverage', 'M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11'],
  ['kb', 'Sources', 'M3 5v14a9 3 0 0 0 18 0V5M3 5a9 3 0 0 0 18 0M3 5a9 3 0 0 1 18 0M3 12a9 3 0 0 0 18 0'],
  ['cases', 'Use cases', 'M5 3l14 9-14 9V3z'],
  ['usecases', 'Config', 'M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6'],
  ['model', 'Model', 'M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z'],
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
  const { chats, activeChatId, openChat, newChat } = useChats()
  const [recents, setRecents] = useState(true)

  return (
    <div className="app">
      <aside className="sidebar" aria-label="Primary">
        <div className="side-brand"><span className="brand">AA</span><span className="side-title">Architecture Atlas</span></div>

        <button className="btn primary side-new" onClick={newChat}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M12 5v14M5 12h14" /></svg>
          New chat
        </button>

        <nav className="side-nav">
          {NAV.map(([to, label, d]) => (
            <NavLink key={to} to={'/' + to} className="side-link" title={label}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d={d} /></svg>
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        <button className="side-recents" onClick={() => setRecents(r => !r)} aria-expanded={recents}>
          <span>Recents</span>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={recents ? 'open' : ''}><path d="M6 9l6 6 6-6" /></svg>
        </button>

        <div className="side-history">
          {recents && (chats.length === 0
            ? <div className="chat-empty">No conversations yet.</div>
            : chats.map(c => (
              <button key={c.id} className={'chat-item' + (c.id === activeChatId ? ' active' : '')} onClick={() => openChat(c.id)}>
                <span className="t">{c.title}</span>
              </button>
            )))}
        </div>

        <button className="iconbtn side-theme" onClick={toggleTheme} title="Toggle theme" aria-label="Toggle theme">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
        </button>
      </aside>
      <div className="view-area"><Outlet /></div>
    </div>
  )
}
