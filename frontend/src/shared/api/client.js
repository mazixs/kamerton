export const apiKeyStorage = "stt_console_key"
export const defaultJsonLimit = 1024 * 1024

export function sameOriginRequest(path, options) {
  if (typeof path !== "string" || !path.startsWith("/") || new URL(path, location.origin).origin !== location.origin) {
    throw new TypeError("Expected a same-origin API path")
  }
  return fetch(path, { ...options, mode: "same-origin", credentials: "same-origin", redirect: "error", cache: "no-store" })
}

export async function readSession(signal) {
  const response = await sameOriginRequest("/auth/session", { signal })
  if (!response.ok) throw new Error("Session lookup failed")
  return response.json()
}

export function isOwnerSession(session) {
  return session?.mode === "owner" && session.authenticated === true &&
    typeof session.csrf_token === "string" && Boolean(session.csrf_token)
}

export function jsonLimitOf(session) {
  return Number.isSafeInteger(session?.json_limit_bytes) && session.json_limit_bytes > 0
    ? session.json_limit_bytes
    : defaultJsonLimit
}

class LocalizedError extends Error {
  constructor(t, key, params) {
    super()
    this.t = t
    this.key = key
    this.params = params
  }

  get message() {
    return this.t(this.key, this.params)
  }
}

export function createApiClient(session, { t, onUnauthorized, onKey, onSession }) {
  const localized = (key, params) => new LocalizedError(t, key, params)
  async function api(path, options = {}, retry = false) {
    const current = session.current
    if (!current.mode || current.leaving) throw localized("auth.unavailable")
    const headers = new Headers(options.headers)
    const method = (options.method ?? "GET").toUpperCase()
    if (current.mode === "local" && current.key) headers.set("Authorization", "Bearer " + current.key)
    if (current.mode === "owner" && !["GET", "HEAD"].includes(method)) headers.set("X-CSRF-Token", current.csrf)
    const response = await sameOriginRequest(path, { ...options, headers })
    if (response.status === 401 && current.mode === "owner") {
      onUnauthorized()
      throw localized("auth.denied")
    }
    if (response.status === 401 && current.mode === "local" && !retry && !current.keyAsked) {
      current.keyAsked = true
      const entered = window.prompt(t("api.keyPrompt"), "")
      if (entered?.trim()) {
        onKey(entered)
        return api(path, options, true)
      }
    }
    if (!response.ok) {
      let error = localized("api.error", { status: response.status })
      let body
      try { body = await response.json() } catch { /* Оставляем код HTTP. */ }
      const code = body?.error?.code
      if (body?.error?.message) {
        const key = "error." + code
        error = t(key) === key ? new Error(body.error.message) : localized(key)
      } else if (body?.detail) {
        error = new Error(typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail))
      }
      // С invalid_csrf сервер еще не успел выполнить операцию.
      if (!retry && current.mode === "owner" && headers.has("X-CSRF-Token") && response.status === 403 && code === "invalid_csrf") {
        options.signal?.throwIfAborted()
        const renewed = await readSession(options.signal)
        options.signal?.throwIfAborted()
        if (!isOwnerSession(renewed)) {
          if (renewed?.authenticated === false) onUnauthorized()
          throw localized("auth.checkFailed")
        }
        onSession(renewed)
        return api(path, options, true)
      }
      error.status = response.status
      throw error
    }
    return response.headers.get("content-type")?.startsWith("application/json") ? response.json() : response.text()
  }
  return api
}
