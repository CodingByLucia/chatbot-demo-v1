import { useState } from 'react'
import { clearAccessCode, setAccessCode, verifyAccessCode } from './api.js'

// Access screen shown before the chat. The submitted code is checked against
// the server right away: a wrong code stays here with an error, a valid one
// is stored and the parent switches to the chat.
function Gate({ onEnter, error }) {
  const [code, setCode] = useState('')
  const [checking, setChecking] = useState(false)
  const [localError, setLocalError] = useState('')

  async function handleSubmit(event) {
    event.preventDefault()
    const trimmed = code.trim()
    if (!trimmed || checking) return
    setChecking(true)
    setLocalError('')
    setAccessCode(trimmed)
    try {
      await verifyAccessCode()
      onEnter()
    } catch (err) {
      clearAccessCode()
      setLocalError(
        err.code === 'ACCESS_DENIED'
          ? 'Wrong access code. Please try again.'
          : err.message || 'Could not verify the code. Please try again.',
      )
    } finally {
      setChecking(false)
    }
  }

  const shownError = localError || error

  return (
    <div className="gate">
      <h1>Cadre Support</h1>
      <p>Enter the access code to start chatting.</p>
      {shownError && <p className="gate-error">{shownError}</p>}
      <form className="gate-form" onSubmit={handleSubmit}>
        <input
          type="password"
          value={code}
          onChange={(event) => setCode(event.target.value)}
          placeholder="Access code"
          aria-label="Access code"
          disabled={checking}
          autoFocus
        />
        <button type="submit" disabled={!code.trim() || checking}>
          {checking ? 'Checking…' : 'Enter'}
        </button>
      </form>
    </div>
  )
}

export default Gate
