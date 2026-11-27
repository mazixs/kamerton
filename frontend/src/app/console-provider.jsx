import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { apiKeyStorage, createApiClient, defaultJsonLimit, isOwnerSession, jsonLimitOf, readSession } from "@/shared/api/client"
import { useLanguage } from "@/shared/i18n"
import { readPage, setPage } from "./routes"
import { ConsoleContext } from "./use-console"

export function ConsoleProvider({ children }) {
  const { lang, t, changeLanguage } = useLanguage()
  const currentTranslation = useRef(t)
  currentTranslation.current = t
  const authority = useRef({ mode: null, csrf: "", key: "", leaving: false, keyAsked: false })
  const [mode, setMode] = useState(null)
  const [key, setKey] = useState("")
  const [sessionError, setSessionError] = useState(false)
  const [jsonLimit, setJsonLimit] = useState(defaultJsonLimit)
  const [page, setCurrentPage] = useState(readPage)
  const [status, setStatus] = useState(null)
  const [statusError, setStatusError] = useState(null)
  const [heads, setHeads] = useState([])
  const [catalog, setCatalog] = useState("loading")
  const [catalogError, setCatalogError] = useState(null)
  const [logs, setLogs] = useState([])
  const [loggingOut, setLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState(false)
  const subscribers = useRef(new Set())
  const headRequest = useRef(0)
  const statusRequest = useRef(0)
  const checkedOut = useRef(false)

  const onUnauthorized = useCallback(() => {
    if (authority.current.leaving) return
    authority.current.leaving = true
    authority.current.csrf = ""
    setMode(null)
    location.replace("/login")
  }, [])

  const onSession = useCallback(session => {
    if (authority.current.leaving) return
    authority.current.csrf = session.csrf_token
    setJsonLimit(jsonLimitOf(session))
  }, [])

  const updateKey = useCallback(value => {
    if (authority.current.mode !== "local") return
    const next = value.trim()
    authority.current.key = next
    setKey(next)
    try { localStorage.setItem(apiKeyStorage, next) } catch { /* Ключ останется во вкладке. */ }
  }, [])

  const api = useMemo(() => createApiClient(authority, {
    t: (...args) => currentTranslation.current(...args),
    onSession,
    onUnauthorized,
    onKey: updateKey,
  }), [onSession, onUnauthorized, updateKey])

  const checkSession = useCallback(async signal => {
    setSessionError(false)
    try {
      const session = await readSession(signal)
      if (signal?.aborted) return
      if (session.mode === "owner") {
        try { localStorage.removeItem(apiKeyStorage) } catch { /* Хранилище отключено. */ }
        if (session.authenticated === false) { onUnauthorized(); return }
        if (!isOwnerSession(session)) throw new Error("Invalid owner session")
        onSession(session)
      } else if (session.mode === "local") {
        let previousKey = ""
        try { previousKey = localStorage.getItem(apiKeyStorage) || "" } catch { /* Хранилище отключено. */ }
        authority.current.key = previousKey
        setKey(previousKey)
      } else throw new Error("Unknown session mode")
      authority.current.mode = session.mode
      setMode(session.mode)
    } catch {
      if (!signal?.aborted) setSessionError(true)
    }
  }, [onSession, onUnauthorized])

  const refreshStatus = useCallback(async () => {
    const sequence = ++statusRequest.current
    try {
      const result = await api("/api/status")
      if (sequence === statusRequest.current) {
        setStatus(result)
        setStatusError(null)
      }
      return result
    } catch (error) {
      if (sequence === statusRequest.current) { setStatus(null); setStatusError(error) }
      return null
    }
  }, [api])

  const loadHeads = useCallback(async () => {
    const sequence = ++headRequest.current
    setCatalog("loading")
    try {
      const { heads: result } = await api("/api/models?lang=" + encodeURIComponent(lang))
      if (sequence === headRequest.current) {
        setHeads(result)
        setCatalog("ready")
        setCatalogError(null)
      }
    } catch (error) {
      if (sequence === headRequest.current) { setCatalog("error"); setCatalogError(error) }
    }
  }, [api, lang])
  const loadCurrentHeads = useRef(loadHeads)
  loadCurrentHeads.current = loadHeads

  const subscribe = useCallback(listener => {
    subscribers.current.add(listener)
    return () => { subscribers.current.delete(listener) }
  }, [])

  const logout = useCallback(async () => {
    if (checkedOut.current || authority.current.leaving) return
    checkedOut.current = true
    setLoggingOut(true)
    setLogoutError(false)
    // Уведомляем открытые формы, чтобы стереть только что выпущенный ключ.
    for (const listener of subscribers.current) listener({ type: "session-logout" })
    try {
      await api("/auth/logout", { method: "POST" })
      onUnauthorized()
    } catch {
      if (!authority.current.leaving) {
        checkedOut.current = false
        setLoggingOut(false)
        setLogoutError(true)
      }
    }
  }, [api, onUnauthorized])

  useEffect(() => {
    const controller = new AbortController()
    checkSession(controller.signal)
    return () => controller.abort()
  }, [checkSession])

  useEffect(() => {
    const onHashChange = () => setCurrentPage(readPage())
    window.addEventListener("hashchange", onHashChange)
    return () => window.removeEventListener("hashchange", onHashChange)
  }, [])

  useEffect(() => {
    if (!mode) return
    refreshStatus()
    const timer = setInterval(refreshStatus, 5000)
    return () => clearInterval(timer)
  }, [mode, key, refreshStatus])

  useEffect(() => {
    if (mode) loadHeads()
  }, [mode, key, loadHeads])

  useEffect(() => {
    if (mode && ["models", "compare"].includes(page)) loadCurrentHeads.current()
  }, [mode, page])

  const previousPhase = useRef(null)
  useEffect(() => {
    const phase = status?.status
    const before = previousPhase.current
    previousPhase.current = phase
    if (mode && phase && before && phase !== before && !["downloading", "starting"].includes(phase)) {
      loadCurrentHeads.current()
    }
  }, [mode, status?.status])

  useEffect(() => {
    if (!mode) return
    let source
    let reconnect
    function connect() {
      if (authority.current.leaving) return
      const query = mode === "local" && key ? "?api_key=" + encodeURIComponent(key) : ""
      source = new EventSource("/api/events" + query)
      source.onmessage = event => {
        let payload
        try { payload = JSON.parse(event.data) } catch { return }
        if (payload.type === "snapshot") {
          setLogs([])
          setStatus(payload)
          setStatusError(null)
          loadCurrentHeads.current()
        } else if (payload.type === "log") {
          setLogs(lines => [...lines.slice(-399), payload.line])
        } else if (payload.type === "status") {
          refreshStatus()
        } else if (payload.type === "download") {
          setStatus(current => ({ ...current, status: "downloading", deploying: payload.variant, download_percent: payload.percent }))
        } else if (payload.type === "diarization") {
          setStatus(current => current && { ...current, diarization: payload, diarization_installed: payload.status === "installed" })
        }
        for (const listener of subscribers.current) listener(payload)
      }
      source.onerror = () => {
        source.close()
        reconnect = setTimeout(connect, 3000)
      }
    }
    connect()
    return () => { source?.close(); clearTimeout(reconnect) }
  }, [mode, key, refreshStatus])

  useEffect(() => {
    if (mode !== "owner") return
    const events = ["pointerdown", "keydown", "input"]
    let lastActivity = -Infinity
    const activity = event => {
      const now = performance.now()
      if (!event.isTrusted || document.hidden || authority.current.leaving || checkedOut.current || now - lastActivity < 60000) return
      lastActivity = now
      api("/auth/activity", { method: "POST" }).catch(() => {})
    }
    const pageShow = event => { if (event.persisted) location.reload() }
    for (const event of events) document.addEventListener(event, activity, { capture: true, passive: true })
    window.addEventListener("pageshow", pageShow)
    return () => {
      for (const event of events) document.removeEventListener(event, activity, true)
      window.removeEventListener("pageshow", pageShow)
    }
  }, [api, mode])

  const value = {
    api, mode, key, updateKey, page, setPage, lang, t, changeLanguage, jsonLimit, checkSession, sessionError,
    logout, loggingOut, logoutError, status, statusError, catalog, heads, catalogError, logs, refreshStatus, loadHeads, subscribe,
  }
  return <ConsoleContext.Provider value={value}>{children}</ConsoleContext.Provider>
}
