import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from './api'

// Shared chat state so the sidebar (shell) and the Ask view agree on which
// conversation is open and the recents list stays fresh.
const Ctx = createContext(null)
export const useChats = () => useContext(Ctx)

export function ChatsProvider({ children }) {
  const [chats, setChats] = useState([])
  const [activeChatId, setActiveChatId] = useState(null)
  const nav = useNavigate()
  const refreshChats = useCallback(
    () => api.chatsList().then(d => setChats(d.chats)).catch(() => {}), [])
  useEffect(() => { refreshChats() }, [refreshChats])

  const openChat = (id) => { setActiveChatId(id); nav('/ask') }   // from the sidebar
  const newChat = () => { setActiveChatId(null); nav('/ask') }

  return (
    <Ctx.Provider value={{ chats, refreshChats, activeChatId, setActiveChatId, openChat, newChat }}>
      {children}
    </Ctx.Provider>
  )
}
