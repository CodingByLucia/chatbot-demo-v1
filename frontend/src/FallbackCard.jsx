import { useState } from 'react'
import { submitContact } from './api.js'

// Card attached to an assistant message when the bot hands off to a human:
// the booking link, plus an optional name/email form so the team can follow up.
function FallbackCard({ chatId, bookingUrl, onAccessDenied }) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(event) {
    event.preventDefault()
    if (sending) return
    setError('')
    setSending(true)
    try {
      await submitContact(chatId, name.trim(), email.trim())
      setSent(true)
    } catch (err) {
      if (err.code === 'ACCESS_DENIED') {
        onAccessDenied()
        return
      }
      setError(err.message || 'Could not send your details. Please try again.')
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="fallback-card">
      <a className="booking-link" href={bookingUrl} target="_blank" rel="noreferrer">
        Book a call
      </a>
      {sent ? (
        <p className="contact-thanks">Thanks! The team will be in touch.</p>
      ) : (
        <form className="contact-form" onSubmit={handleSubmit}>
          <p className="contact-hint">
            Or leave your details and the team will reach out:
          </p>
          {error && <p className="contact-error">{error}</p>}
          <div className="contact-fields">
            <input
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Name"
              aria-label="Name"
              disabled={sending}
            />
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="Email"
              aria-label="Email"
              disabled={sending}
            />
            <button
              type="submit"
              disabled={sending || !name.trim() || !email.trim()}
            >
              {sending ? 'Sending…' : 'Send'}
            </button>
          </div>
        </form>
      )}
    </div>
  )
}

export default FallbackCard
