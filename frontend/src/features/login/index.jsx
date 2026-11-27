import { useEffect, useRef, useState } from "react"
import { createRoot } from "react-dom/client"
import { Brand } from "@/components/brand"
import { IconDefinitions } from "@/components/icons"
import { LanguageSwitch } from "@/components/language-switch"
import { Heading, Layout, Paragraph } from "@/components/native/layout"
import { Button } from "@/components/ui/button"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { apiKeyStorage, isOwnerSession, readSession, sameOriginRequest } from "@/shared/api/client"
import { useLanguage } from "@/shared/i18n"
import "@/styles/theme.css"
import "@/styles/shell.css"
import "@/styles/access.css"

function Login() {
  const language = useLanguage()
  const { t } = language
  const password = useRef(null)
  const pending = useRef(false)
  const [busy, setBusy] = useState(false)
  const [checking, setChecking] = useState(true)
  const [error, setError] = useState("")

  useEffect(() => {
    const controller = new AbortController()
    try { localStorage.removeItem(apiKeyStorage) } catch { /* Хранилище отключено. */ }
    readSession(controller.signal).then(session => {
      if (isOwnerSession(session)) location.replace("/")
    }).catch(() => {
      if (!controller.signal.aborted) setError("auth.checkFailed")
    }).finally(() => {
      if (!controller.signal.aborted) setChecking(false)
    })
    function onHide() { if (password.current) password.current.value = "" }
    function onShow(event) { if (event.persisted) location.reload() }
    window.addEventListener("pagehide", onHide)
    window.addEventListener("pageshow", onShow)
    return () => {
      controller.abort()
      window.removeEventListener("pagehide", onHide)
      window.removeEventListener("pageshow", onShow)
    }
  }, [])

  useEffect(() => { document.title = t("auth.title") + " - " + t("brand.name") }, [t])

  async function signIn(event) {
    event.preventDefault()
    if (checking || pending.current) return
    const fields = new FormData(event.currentTarget)
    pending.current = true
    setBusy(true)
    setError("")
    try {
      const response = await sameOriginRequest("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Kamerton-Login": "1" },
        body: JSON.stringify({ username: fields.get("username"), password: fields.get("password") }),
      })
      if (response.ok && isOwnerSession(await response.json())) {
        password.current.value = ""
        location.replace("/")
        return
      }
      setError(response.status === 401 ? "auth.denied" : response.status === 429 ? "auth.limited" : "auth.unavailable")
      if (response.status === 401) {
        password.current.value = ""
        password.current.focus()
      }
    } catch {
      setError("auth.unavailable")
    } finally {
      pending.current = false
      setBusy(false)
    }
  }

  return (
    <>
      <IconDefinitions />
      <header className="login-header"><Brand t={t} /><LanguageSwitch {...language} /></header>
      <Layout role="main" variant="login-main">
        <header className="pagehead"><Heading level={1}>{t("auth.title")}</Heading><Paragraph>{t("auth.intro")}</Paragraph></header>
        <form id="login-form" className="panel" action="/auth/login" method="post" onSubmit={signIn}>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="login-username">{t("auth.username")}</FieldLabel>
              <Input id="login-username" name="username" autoComplete="username" autoCapitalize="none" autoCorrect="off" spellCheck={false} required />
            </Field>
            <Field data-invalid={error === "auth.denied" || undefined}>
              <FieldLabel htmlFor="login-password">{t("auth.password")}</FieldLabel>
              <Input ref={password} id="login-password" name="password" autoComplete="current-password" type="password"
                aria-invalid={error === "auth.denied" || undefined} aria-describedby={error ? "login-error" : undefined} required />
            </Field>
            <p id="login-error" className="error" role="alert">{error && t(error)}</p>
            <Button id="login-submit" type="submit" disabled={busy || checking}>{t(busy ? "auth.signingIn" : "auth.signIn")}</Button>
          </FieldGroup>
        </form>
      </Layout>
    </>
  )
}

createRoot(document.getElementById("root")).render(<Login />)
