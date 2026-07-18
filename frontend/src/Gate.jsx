import { useState } from 'react'
import { setAccessCode } from './api.js'

// Access screen shown before the chat. Stores the submitted code and tells
// the parent to switch to the chat; the code itself is only validated by the
// first real API call.
function Gate({ onEnter, error }) {
  const [code, setCode] = useState('')

  function handleSubmit(event) {
    event.preventDefault()
    const trimmed = code.trim()
    if (!trimmed) return
    setAccessCode(trimmed)
    onEnter()
  }

  return (
    <div className="gate">
      <h1>Cadre Support</h1>
      <p>Enter the access code to start chatting.</p>
      {error && <p className="gate-error">{error}</p>}
      <form className="gate-form" onSubmit={handleSubmit}>
        <input
          type="password"
          value={code}
          onChange={(event) => setCode(event.target.value)}
          placeholder="Access code"
          aria-label="Access code"
          autoFocus
        />
        <button type="submit" disabled={!code.trim()}>
          Enter
        </button>
      </form>
    </div>
  )
}

export default Gate
