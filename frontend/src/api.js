// All backend communication lives here. Components import these functions
// and never call fetch directly.

const ACCESS_CODE_KEY = 'cadre_access_code'

export function getAccessCode() {
  return sessionStorage.getItem(ACCESS_CODE_KEY)
}

export function setAccessCode(code) {
  sessionStorage.setItem(ACCESS_CODE_KEY, code)
}

export function clearAccessCode() {
  sessionStorage.removeItem(ACCESS_CODE_KEY)
}

// The active conversation id survives a page refresh in sessionStorage.
const CHAT_ID_KEY = 'cadre_chat_id'

export function getStoredChatId() {
  return sessionStorage.getItem(CHAT_ID_KEY)
}

export function setStoredChatId(chatId) {
  sessionStorage.setItem(CHAT_ID_KEY, chatId)
}

export function clearStoredChatId() {
  sessionStorage.removeItem(CHAT_ID_KEY)
}

// Error thrown for every failed call. Carries the HTTP status plus the
// server's {code, message} body so callers can switch on `code`.
export class ApiError extends Error {
  constructor(status, code, message) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

// Sends a request with the stored access code attached, returns the parsed
// JSON body on success and throws an ApiError otherwise.
async function request(path, options = {}) {
  let response
  try {
    response = await fetch(path, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        'X-Access-Code': getAccessCode() ?? '',
      },
    })
  } catch {
    throw new ApiError(
      0,
      'NETWORK',
      'Could not reach the server. Check your connection and try again.',
    )
  }

  let body
  try {
    body = await response.json()
  } catch {
    body = null
  }

  if (!response.ok) {
    if (body && body.code && body.message) {
      throw new ApiError(response.status, body.code, body.message)
    }
    throw new ApiError(
      response.status,
      'NETWORK',
      'Something went wrong. Please try again.',
    )
  }

  if (body === null) {
    throw new ApiError(
      response.status,
      'NETWORK',
      'The server returned an unreadable response. Please try again.',
    )
  }

  return body
}

// Starts a new conversation with the first user message.
export function startChat(message) {
  return request('/api/v1/chat', {
    method: 'POST',
    body: JSON.stringify({ message }),
  })
}

// Sends a follow-up message in an existing conversation.
export function sendMessage(chatId, message) {
  return request(`/api/v1/chat/${encodeURIComponent(chatId)}/messages`, {
    method: 'POST',
    body: JSON.stringify({ message }),
  })
}

// Fetches the full message history of a conversation.
export function getChat(chatId) {
  return request(`/api/v1/chat/${encodeURIComponent(chatId)}`)
}

// Leaves the visitor's name and email from the fallback card.
export function submitContact(chatId, name, email) {
  return request(`/api/v1/chat/${encodeURIComponent(chatId)}/contact`, {
    method: 'POST',
    body: JSON.stringify({ name, email }),
  })
}
