import { useEffect, useRef, useState } from 'react'
import Gate from './Gate.jsx'
import FallbackCard from './FallbackCard.jsx'
import {
  clearAccessCode,
  clearStoredChatId,
  getAccessCode,
  getChat,
  getStoredChatId,
  sendMessage,
  setStoredChatId,
  startChat,
} from './api.js'
import './App.css'

function App() {
  const [hasCode, setHasCode] = useState(() => Boolean(getAccessCode()))
  const [gateError, setGateError] = useState('')
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  // True while the previous conversation is being fetched after a reload.
  const [restoring, setRestoring] = useState(
    () => Boolean(getAccessCode()) && Boolean(getStoredChatId()),
  )
  const [banner, setBanner] = useState('')
  const [chatId, setChatId] = useState(() => getStoredChatId())
  const bottomRef = useRef(null)

  // Keeps the newest message (or the loading bubble) in view.
  useEffect(() => {
    bottomRef.current?.scrollIntoView()
  }, [messages, loading])

  // Drops the stored code and sends the user back to the gate.
  function handleAccessDenied() {
    clearAccessCode()
    setGateError('Wrong or expired access code. Please enter it again.')
    setHasCode(false)
  }

  // Restores the conversation stored from a previous page load, so a
  // refresh doesn't wipe the chat.
  useEffect(() => {
    if (!hasCode) return
    const storedId = getStoredChatId()
    if (!storedId) return
    let cancelled = false
    getChat(storedId)
      .then((history) => {
        if (cancelled) return
        setChatId(history.chat_id)
        // Anything already typed locally wins over the fetched history.
        setMessages((prev) => (prev.length ? prev : history.messages))
      })
      .catch((err) => {
        if (cancelled) return
        if (err.code === 'ACCESS_DENIED') {
          handleAccessDenied()
        } else if (err.code === 'UNKNOWN_CHAT') {
          clearStoredChatId()
          setChatId(null)
        } else {
          setBanner(err.message || 'Could not restore the conversation.')
        }
      })
      .finally(() => {
        if (!cancelled) setRestoring(false)
      })
    return () => {
      cancelled = true
    }
  }, [hasCode])

  function adoptChatId(id) {
    setChatId(id)
    setStoredChatId(id)
  }

  function handleNewChat() {
    clearStoredChatId()
    setChatId(null)
    setMessages([])
    setBanner('')
  }

  async function handleSend(event) {
    event.preventDefault()
    const text = input.trim()
    if (!text || loading || restoring) return

    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setInput('')
    setBanner('')
    setLoading(true)

    try {
      const response = chatId
        ? await sendMessage(chatId, text)
        : await startChat(text)
      adoptChatId(response.chat_id)
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: response.reply, fallback: response.fallback },
      ])
    } catch (err) {
      // Take the unanswered message back out of the list and put its text
      // back in the input so the user can send it again.
      setMessages((prev) => prev.slice(0, -1))
      setInput(text)

      if (err.code === 'ACCESS_DENIED') {
        handleAccessDenied()
      } else if (err.code === 'UNKNOWN_CHAT') {
        clearStoredChatId()
        setChatId(null)
        setBanner(
          'This conversation expired. Your next message will start a new one.',
        )
      } else {
        setBanner(err.message || 'Something went wrong. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }

  if (!hasCode) {
    return (
      <Gate
        error={gateError}
        onEnter={() => {
          setGateError('')
          setHasCode(true)
        }}
      />
    )
  }

  return (
    <div className="app">
      <header className="header">
        <h1>Cadre Support</h1>
        <button
          type="button"
          className="new-chat"
          onClick={handleNewChat}
          disabled={loading || restoring || (messages.length === 0 && !chatId)}
        >
          New chat
        </button>
      </header>

      {banner && (
        <div className="banner" role="alert">
          <span>{banner}</span>
          <button
            type="button"
            className="banner-close"
            aria-label="Dismiss"
            onClick={() => setBanner('')}
          >
            &times;
          </button>
        </div>
      )}

      <main className="messages">
        {restoring && <p className="empty-hint">Loading conversation…</p>}
        {messages.length === 0 && !loading && !restoring && (
          <p className="empty-hint">Ask a question about Cadre to get started.</p>
        )}
        {messages.map((message, index) => (
          <div key={index} className={`message ${message.role}`}>
            <div className={`bubble ${message.role}`}>{message.content}</div>
            {message.fallback && (
              <FallbackCard
                chatId={chatId}
                bookingUrl={message.fallback.booking_url}
                onAccessDenied={handleAccessDenied}
              />
            )}
          </div>
        ))}
        {loading && (
          <div className="message assistant">
            <div className="bubble assistant thinking">Thinking…</div>
          </div>
        )}
        <div ref={bottomRef} />
      </main>

      <form className="input-row" onSubmit={handleSend}>
        <input
          type="text"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Type your message…"
          aria-label="Message"
          disabled={loading || restoring}
          autoFocus
        />
        <button type="submit" disabled={loading || restoring || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  )
}

export default App
