import { useEffect, useRef, useState } from "react"

import { useConsole } from "@/app/use-console"
import { Layout, Paragraph } from "@/components/native/layout"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

import { downloadReason, formatDiskBytes } from "./model-state"

export function Diarizer() {
  const { api, status, refreshStatus, t, lang } = useConsole()
  const details = useRef(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)
  const info = status?.diarization
  const downloading = info?.status === "downloading" || pending
  const installed = info?.status === "installed"
  const percent = Number.isFinite(info?.progress) ? info.progress : undefined
  const message = info?.status === "error" ? downloadReason(info, t) : error?.message

  useEffect(() => {
    if (message && details.current) details.current.open = true
  }, [message])

  async function install() {
    if (downloading) return
    setPending(true)
    setError(null)
    try {
      await api("/api/models/diarization", { method: "POST" })
    } catch (reason) {
      setError(reason)
    } finally {
      await refreshStatus()
      setPending(false)
    }
  }

  if (!info?.available) return null
  return (
    <details id="models-diarizers" className="modelgroup" aria-labelledby="family-diarizers" ref={details}>
      <summary><span id="family-diarizers">{t("diarization.catalog")}</span><Badge variant="secondary" className="family-count" aria-hidden="true">1</Badge></summary>
      <Layout variant="diarizer-row">
        <Layout><strong>Nemotron-3 Diarization</strong><Paragraph variant="help">{t("diarization.installed")}</Paragraph></Layout>
        <span className="small" id="diarizer-size">{formatDiskBytes(info.bytes, t, lang)}</span>
        <Button type="button" variant="ghost" id="diarizer-install" disabled={downloading} hidden={installed} onClick={install}>
          {t("diarization.install")}
        </Button>
        <Layout variant="diarizer-progress">
          <progress id="diarizer-progress" max="100" value={percent} aria-labelledby="diarizer-state" hidden={!downloading} />
          <p id="diarizer-state" className={cn("help", message && "error")} role="status">
            {downloading ? [t("state.downloading"), percent == null ? "" : percent + "%"].filter(Boolean).join(" · ")
              : message || t(installed ? "head.downloaded" : "models.notDownloaded")}
          </p>
        </Layout>
      </Layout>
    </details>
  )
}
