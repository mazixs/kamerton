import { useEffect, useRef, useState } from "react"

import { useConsole } from "@/app/use-console"
import { Heading, Layout, Paragraph } from "@/components/native/layout"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { RETENTION_VALUES, historyRetention, setHistoryRetention } from "@/lib/history-retention"

export function Settings() {
  const { api, mode, status, refreshStatus, t } = useConsole()
  const [retention, setRetention] = useState(historyRetention)
  const [storageError, setStorageError] = useState(false)
  const [pending, setPending] = useState(null)
  const [error, setError] = useState(null)
  const saving = useRef(false)
  const comparable = status?.compare_enabled === true
  const protectedMode = mode === "owner" || Boolean(status?.api_key_set)
  const available = status?.compare_available ?? protectedMode
  const comparisonDisabled = !status || (!available && !comparable) || pending !== null
  const comparisonNote = !status || available ? "compare.toggleNote" : protectedMode ? "compare.noTemp" : "compare.needsKey"

  useEffect(() => {
    const sync = () => setRetention(historyRetention())
    window.addEventListener("storage", sync)
    return () => window.removeEventListener("storage", sync)
  }, [])

  function saveRetention(event) {
    try {
      setHistoryRetention(event.currentTarget.value)
      setStorageError(false)
    } catch {
      setStorageError(true)
    }
    setRetention(historyRetention())
  }

  async function toggleComparison(event) {
    if (saving.current) return
    const enabled = event.currentTarget.checked
    saving.current = true
    setPending(enabled)
    setError(null)
    try {
      await api("/api/settings/compare", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      })
    } catch (reason) {
      setError(reason)
    } finally {
      await refreshStatus()
      setPending(null)
      saving.current = false
    }
  }

  return (
    <>
      <Layout variant="stack preferences-section" role="region" aria-labelledby="history-preference-title">
        <Heading level={2} id="history-preference-title">{t("settings.history")}</Heading>
        <FieldGroup className="stack">
          <Field className="setting">
            <FieldLabel htmlFor="history-retention">{t("settings.retention")}</FieldLabel>
            <NativeSelect id="history-retention" value={retention} onChange={saveRetention} aria-describedby="history-storage-note">
              {[...RETENTION_VALUES].map((value) => (
                <NativeSelectOption value={value} key={value}>{t("settings.retention." + value)}</NativeSelectOption>
              ))}
            </NativeSelect>
            <FieldDescription className="help" id="history-storage-note">{t("settings.historyHint")}</FieldDescription>
          </Field>
        </FieldGroup>
        <p id="history-preference-status" className="error" role="status">{storageError ? t("history.storageFailed") : ""}</p>
      </Layout>
      <Layout variant="stack preferences-section" role="region" aria-labelledby="compare-preference-title">
        <Heading level={2} id="compare-preference-title">{t("page.compare")}</Heading>
        <FieldGroup className="stack">
          <Field orientation="horizontal" data-disabled={comparisonDisabled || undefined}>
            <input type="checkbox" id="compare-enabled" checked={pending ?? comparable} onChange={toggleComparison}
              disabled={comparisonDisabled} aria-describedby="compare-toggle-note" />
            <FieldLabel htmlFor="compare-enabled">{t("compare.toggle")}</FieldLabel>
          </Field>
        </FieldGroup>
        <Paragraph variant="help" id="compare-toggle-note">{t(comparisonNote)}</Paragraph>
        <p className="error" role="status" id="compare-toggle-error">{error?.message}</p>
      </Layout>
    </>
  )
}
