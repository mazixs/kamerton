import { useEffect, useRef, useState } from "react"

import { useConsole } from "@/app/use-console"
import { Heading, Layout } from "@/components/native/layout"
import { Button } from "@/components/ui/button"

import { Diarizer } from "./diarizer"
import { ModelCatalog, ModelDescription } from "./model-catalog"
import { envWindowConflict, modelProfile } from "./model-config"
import { deployBusy, detailText, modelFailure } from "./model-state"
import { StartupDialog } from "./startup-dialog"

function errorText(error, t) {
  if (error?.key) return error.message
  return error?.status ? t("api.error", { status: error.status }) : t("models.noConnection")
}

function EnvDifference({ env, busy, pending, error, launch, t }) {
  const conflict = envWindowConflict(env?.config)
  const divergences = Object.entries(env?.diverges || {})
  const valueText = (value) => typeof value === "boolean" ? t(value ? "env.value.on" : "env.value.off") : String(value)
  return (
    <Layout id="env-diff" variant="env-diff" hidden={!divergences.length && !conflict}>
      <Heading level={2}>{t("env.title")}</Heading>
      <ul id="env-diff-list">
        {divergences.map(([name, { env: requested, state }]) => (
          <li key={name} className="mono">{t("env.line", {
            field: t("field." + name), env: valueText(requested), state: valueText(state),
          })}</li>
        ))}
      </ul>
      <Button type="button" variant="outline" id="btn-deploy-env" aria-describedby="env-error"
        disabled={!env?.config || busy || pending || conflict} onClick={() => launch(env.config, true)}>
        {t("env.deploy")}
      </Button>
      <p className="error" id="env-error" role="status">{conflict
        ? t("env.windowsConflict", { windows: env.config.file_window_concurrency, pool: env.config.pool_size })
        : error ? errorText(error, t) : ""}</p>
    </Layout>
  )
}

export function Models({ active }) {
  const { api, status, statusError, heads, catalog, catalogError, refreshStatus, loadHeads, t, lang } = useConsole()
  const dialog = useRef(null)
  const inFlight = useRef(false)
  const [choice, setChoice] = useState(null)
  const [drafts, setDrafts] = useState({})
  const [request, setRequest] = useState(null)
  const selected = choice || status?.defaults?.variant
  const head = heads.find(({ id }) => id === selected)
  const profile = modelProfile(status, selected)
  const draft = drafts[selected]
  const config = { ...profile, ...draft }
  const hasDraft = Boolean(draft && Object.entries(draft).some(([key, value]) =>
    String(profile[key] ?? "") !== String(value ?? "")))
  const busy = deployBusy(status?.status)
  const pending = request?.pending === true
  const failures = Object.fromEntries(heads.map(({ id }) => [
    id,
    request?.variant === id && request.error && !(busy && status.deploying === id)
      ? errorText(request.error, t) : modelFailure(id, status, t),
  ]))
  const progress = status?.status === "downloading" && Number.isFinite(status.download_percent)
    ? status.download_percent + "%" : ""
  const feedback = pending ? t("settings.wait")
    : busy ? [detailText(status, t), status.deploying, progress].filter(Boolean).join(" · ")
    : request?.error && !request.fromEnv ? errorText(request.error, t)
    : request && !request.fromEnv && status ? detailText(status, t) : ""
  const errorStatus = catalogError?.status
  const catalogMessage = catalog === "loading" ? t("models.catalogRetrying")
    : [t(heads.length ? "models.catalogStale" : "models.catalogFailed"),
      errorStatus ? "HTTP " + errorStatus : catalogError instanceof TypeError ? t("models.noConnection") : "",
    ].filter(Boolean).join(" ")

  useEffect(() => {
    if (!active && dialog.current?.open) dialog.current.close()
  }, [active])

  useEffect(() => {
    if (!draft || hasDraft) return
    setDrafts((items) => {
      if (items[selected] !== draft) return items
      const next = { ...items }
      delete next[selected]
      return next
    })
  }, [draft, hasDraft, selected])

  function edit(patch) {
    setDrafts((items) => ({ ...items, [selected]: { ...items[selected], ...patch } }))
  }

  function configure() {
    setChoice(selected)
    dialog.current.showModal()
  }

  async function launch(config, fromEnv = false) {
    if (!config?.variant || inFlight.current || busy) return
    inFlight.current = true
    setRequest({ variant: config.variant, fromEnv, pending: true })
    let error = null
    try {
      await api("/api/deploy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      })
      if (fromEnv) {
        setChoice(null)
        setDrafts((items) => {
          const next = { ...items }
          delete next[config.variant]
          return next
        })
      }
    } catch (reason) {
      error = reason
    } finally {
      await refreshStatus()
      inFlight.current = false
      setRequest({ variant: config.variant, fromEnv, pending: false, error })
    }
  }

  return (
    <>
      <Layout variant="stack" id="catalog-notice" hidden={!catalogError}>
        <p className="error" id="catalog-message" role="status">{catalogError ? catalogMessage : ""}</p>
        <Button type="button" variant="ghost" id="catalog-retry" disabled={catalog === "loading"} onClick={loadHeads}>
          {t("head.retry")}
        </Button>
      </Layout>
      <Layout variant="modelwork">
        <ModelDescription head={head} ready={Boolean(status?.defaults)} onConfigure={configure} t={t} lang={lang} />
        <ModelCatalog {...{ heads, selected, status, failures, t, lang }} ready={Boolean(status?.defaults)} select={setChoice} />
        <Diarizer />
      </Layout>
      <EnvDifference env={status?.env} {...{ busy, pending, launch, t }} error={request?.fromEnv ? request.error : null} />
      <StartupDialog {...{ dialog, head, config, status, statusError, pending, busy, hasDraft, feedback, t }} change={edit} submit={launch} />
    </>
  )
}
