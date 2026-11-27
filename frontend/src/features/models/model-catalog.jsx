import { useEffect, useRef } from "react"

import { Heading, Layout, Paragraph } from "@/components/native/layout"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { FieldLegend, FieldSet } from "@/components/ui/field"
import { cn } from "@/lib/utils"

import { deployBusy, formatDiskBytes } from "./model-state"

const groups = [
  { id: "gigastt", label: "GigaAM", titleId: "gigaam", initialOpen: true },
  { id: "whisper", label: "Whisper", titleId: "whisper" },
  { id: "parakeet", label: "NVIDIA", titleId: "nvidia" },
  { id: "other", message: "models.other", titleId: "other", initialOpen: true },
]

const runtimeNames = {
  gigastt: "GigaSTT",
  gigaam_v4: "PyTorch (CPU)",
  whisper: "whisper.cpp",
  parakeet: "parakeet.cpp",
  sherpa: "sherpa-onnx",
}

function ModelTitle({ title }) {
  const match = title.match(/\(\d{4}-\d{2}-\d{2}\)$/)
  return match ? <>{title.slice(0, match.index)}<span className="modeldate">{match[0]}</span></> : title
}

export function ModelDescription({ head, ready, onConfigure, t, lang }) {
  if (!head) return null
  const languageNames = new Intl.DisplayNames(lang, { type: "language" })
  const languages = head.languages?.length > 5
    ? head.languages.map(code => languageNames.of(code)).join(", ")
    : ""
  return (
    <section className="modeldetail" id="model-detail" aria-labelledby="head-name">
      <Layout>
        <Paragraph variant="modelcaption">{t("models.selected")}</Paragraph>
        <Heading level={2} id="head-name"><ModelTitle title={head.title} /></Heading>
        <Paragraph variant="identity" id="head-meta"><code>{head.id}</code>{runtimeNames[head.runtime] && <span>{runtimeNames[head.runtime]}</span>}</Paragraph>
      </Layout>
      <Layout variant="modeldescription">
        <Paragraph id="head-description">{head.subtitle}</Paragraph>
        {languages && <Paragraph variant="help" id="head-languages">{languages}</Paragraph>}
        <Paragraph variant="head-badge" id="head-badge">{head.badge}</Paragraph>
        <Paragraph variant="help" id="head-note">{head.badge_note}</Paragraph>
      </Layout>
      <Button variant="outline" id="model-settings" type="button" hidden={!ready} onClick={onConfigure}>
        {t("models.configure")}
      </Button>
    </section>
  )
}

function ModelRow({ head, selected, ready, status, select, error, t, lang }) {
  const id = "target-" + head.id
  const running = status?.engine?.running && status.engine.variant === head.id
  const active = running && (status.status === "ready" || status.detail_params?.running === head.id)
  const readiness = !status ? t("models.unknownState")
    : status.deploying === head.id && deployBusy(status.status) ? t("state." + status.status)
    : active ? t("models.active") : running ? t("models.process") : ""
  const codes = (head.languages || []).join(", ").toUpperCase()
  const language = head.languages?.length > 5 ? t("models.languageCount", { count: head.languages.length })
    : codes === "RU" ? t("models.russian")
    : ["whisper", "parakeet"].includes(head.runtime) ? t("models.includingLanguages", { languages: codes })
    : codes
  const size = head.downloaded && Number.isFinite(head.installed_bytes)
    ? t("storage.installed", { size: formatDiskBytes(head.installed_bytes, t, lang) })
    : t("head.size", { mb: head.size_mb })

  return (
    <label className="modelrow">
      <input id={id} type="radio" name="target-model" value={head.id} checked={selected}
        disabled={!ready} onChange={() => select(head.id)} aria-labelledby={id + "-title"}
        aria-describedby={["modellang", "modelsize", "modelstate", "modelerror"].map((key) => id + "-" + key).join(" ")} />
      <span className="modeltitle" id={id + "-title"}><ModelTitle title={head.title} /></span>
      <span className="modellang" id={id + "-modellang"}>{language}</span>
      <span className="modelsize" id={id + "-modelsize"}>{size}</span>
      <span className={cn("modelstate", active && "active-model")} id={id + "-modelstate"}>
        {[readiness, t(head.downloaded ? "head.downloaded" : "models.notDownloaded")].filter(Boolean).join(" · ")}
      </span>
      <span className="modelerror" id={id + "-modelerror"}>{error}</span>
    </label>
  )
}

function ModelGroup({ group, members, selected, ready, status, select, failures, t, lang }) {
  const disclosure = useRef(null)
  const openedForSelection = useRef(false)
  const selectedHere = members.some((head) => head.id === selected)
  const failureId = members.find(({ id }) => failures[id])?.id
  const errorSignature = failureId ? failureId + failures[failureId] : ""
  const titleId = "family-" + group.titleId

  useEffect(() => {
    if (ready && selectedHere && !openedForSelection.current) {
      disclosure.current.open = true
      openedForSelection.current = true
    }
  }, [ready, selectedHere])

  useEffect(() => {
    if (errorSignature) disclosure.current.open = true
  }, [errorSignature])

  return (
    <details className="modelgroup" id={"models-" + group.id} ref={disclosure} open={group.initialOpen || undefined}
      aria-labelledby={titleId} hidden={!members.length}>
      <summary>
        <span id={titleId}>{group.label || t(group.message)}</span>
        <Badge variant="secondary" className="family-count" aria-hidden="true">{members.length}</Badge>
      </summary>
      {members.map((head) => <ModelRow key={head.id} {...{ head, ready, status, select, t, lang }}
        selected={head.id === selected} error={failures[head.id]} />)}
    </details>
  )
}

export function ModelCatalog({ heads, selected, ready, status, select, failures, t, lang }) {
  const members = { gigastt: [], whisper: [], parakeet: [], other: [] }
  for (const head of heads) {
    const family = head.runtime === "gigaam_v4" ? "gigastt" : head.runtime ?? "gigastt"
    const familyMembers = members[family] || members.other
    familyMembers.push(head)
  }

  return (
    <FieldSet>
      <FieldLegend className="catalog-legend">{t("section.models")}</FieldLegend>
      <Layout variant="modelcolumns" aria-hidden="true">
        {["model", "languages", "weights", "state"].map((key) => <span key={key}>{t("models." + key)}</span>)}
      </Layout>
      <Layout variant="modelrows" id="heads">
        {groups.map((group) => <ModelGroup key={group.id} {...{ group, selected, ready, status, select, failures, t, lang }}
          members={members[group.id]} />)}
      </Layout>
    </FieldSet>
  )
}
