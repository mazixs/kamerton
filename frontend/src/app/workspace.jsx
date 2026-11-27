import { lazy, Suspense, useEffect, useRef, useState } from "react"
import { IconDefinitions } from "@/components/icons"
import { Heading, Layout, Paragraph } from "@/components/native/layout"
import { Button } from "@/components/ui/button"
import { MobileHeader, Sidebar } from "./sidebar"
import { useConsole } from "./use-console"

const pages = [
  ["dict", "dictwork", lazy(() => import("@/features/dictation").then(m => ({ default: m.Dictation })))],
  ["compare", "sections", lazy(() => import("@/features/compare").then(m => ({ default: m.Compare })))],
  ["benchmarks", "sections", lazy(() => import("@/features/benchmarks").then(m => ({ default: m.Benchmarks })))],
  ["api", "apiwork panelgrid", lazy(() => import("@/features/connection").then(m => ({ default: m.Connection })))],
  ["models", "sections", lazy(() => import("@/features/models").then(m => ({ default: m.Models })))],
  ["settings", "preferences", lazy(() => import("@/features/settings").then(m => ({ default: m.Settings })))],
  ["glossary", "sections", lazy(() => import("@/features/glossary").then(m => ({ default: m.Glossary })))],
  ["status", "sections", lazy(() => import("@/features/status").then(m => ({ default: m.ServiceStatus })))],
  ["journal", "sections", lazy(() => import("@/features/journal").then(m => ({ default: m.Journal })))],
]

function ConsolePages() {
  const { page, t } = useConsole()
  const [visited, setVisited] = useState(() => new Set([page]))
  useEffect(() => { setVisited(previous => previous.has(page) ? previous : new Set([...previous, page])) }, [page])
  return pages.map(([route, className, Screen]) => (
    <section key={route} data-page={route} className={className} hidden={route !== page} aria-labelledby="heading">
      {(route === page || visited.has(route)) && (
        <Suspense fallback={<p role="status" className="help">{t("state.loading")}</p>}>
          <Screen active={route === page} />
        </Suspense>
      )}
    </section>
  ))
}

export function Workspace() {
  const { mode, page, t, sessionError, checkSession, logout, loggingOut, logoutError } = useConsole()
  const main = useRef(null)
  const lastPage = useRef(page)
  useEffect(() => {
    document.title = t("page." + page) + " - " + t("brand.name")
    if (lastPage.current !== page) {
      main.current?.focus({ preventScroll: true })
      window.scrollTo(0, 0)
      lastPage.current = page
    }
  }, [page, t])

  if (!mode) return (
    <Layout id="session-check" variant="session-check">
      <p id="session-message" role="status">{t(sessionError ? "auth.checkFailed" : "auth.checking")}</p>
      <Button type="button" id="session-retry" hidden={!sessionError} onClick={() => checkSession()}>
        {t("head.retry")}
      </Button>
    </Layout>
  )
  return (
    <>
      <a className="skip" href="#main" onClick={event => { event.preventDefault(); main.current?.focus() }}>{t("nav.skip")}</a>
      <IconDefinitions />
      <Layout variant="shell">
        <Sidebar />
        <Layout variant="frame">
          <MobileHeader />
          <Layout role="main" id="main" ref={main} tabIndex={-1}>
            <header className="pagehead">
              <Layout variant="titleline">
                <Heading level={1} id="heading">{t("page." + page)}</Heading>
                {mode === "owner" && <Button id="owner-logout" variant="ghost" disabled={loggingOut} onClick={logout}>{t("auth.logout")}</Button>}
              </Layout>
              <p id="logout-error" className="error" role="alert">{logoutError && t("auth.logoutFailed")}</p>
              <Paragraph id="intro">{t("intro." + page)}</Paragraph>
            </header>
            <ConsolePages />
          </Layout>
        </Layout>
      </Layout>
    </>
  )
}
