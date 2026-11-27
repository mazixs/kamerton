import { Heading, Layout, Paragraph } from "@/components/native/layout"
import { Button } from "@/components/ui/button"
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldLegend, FieldSet } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"

import { modelDraft } from "./model-config"

const counts = Array.from({ length: 8 }, (_, index) => index + 1)

function FieldControl({ id, label, noteId, note, disabled, children }) {
  return (
    <Field className="setting" data-disabled={disabled || undefined}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      {children}
      <FieldDescription id={noteId} className="help">{note}</FieldDescription>
    </Field>
  )
}

function OptionSetting({ id, label, noteId, note, items, value, onChange, disabled }) {
  return (
    <FieldControl {...{ id, label, noteId, note, disabled }}>
      <NativeSelect id={id} value={value} onChange={onChange} aria-describedby={noteId} disabled={disabled}>
        {items.map(([key, title, unavailable]) => (
          <NativeSelectOption key={String(key)} value={String(key)} disabled={unavailable}>{title}</NativeSelectOption>
        ))}
      </NativeSelect>
    </FieldControl>
  )
}

function NumberSetting({ id, label, noteId, note, value, onChange, disabled, ...props }) {
  return (
    <FieldControl {...{ id, label, noteId, note, disabled }}>
      <Input id={id} value={value} onChange={onChange} type="number" aria-describedby={noteId} disabled={disabled} {...props} />
    </FieldControl>
  )
}

export function StartupDialog({ dialog, head, config, change, status, statusError, pending, busy, hasDraft, feedback, submit, t }) {
  const runtime = head?.runtime || "gigastt"
  const alternate = runtime !== "gigastt"
  const options = (values, key) => values.map((value) => [value, t(key + value)])
  const modes = options(["auto", "on", "off"], "mode.")
  const pool = Number(config.pool_size ?? 1)
  const noHints = status?.glossary_count === 0 && config.hotwords_default === false
  const set = (name, read = (value) => value) => (event) => change({ [name]: read(event.currentTarget.value) })
  const changePool = (event) => {
    const next = Number(event.currentTarget.value)
    change({ pool_size: next, file_window_concurrency: Math.min(next, Number(config.file_window_concurrency ?? 1)) })
  }
  const optionsWithCounts = (key) => counts.map((value) => {
    const label = t(key + value)
    return [value, label === key + value ? value : label]
  })
  const hintMode = head?.id === "rnnt" ? "autoOn" : head?.native_punctuation ? "native" : "autoOff"
  const percent = status?.status === "downloading" && Number.isFinite(status.download_percent)
    ? status.download_percent
    : null

  function handleSubmit(event) {
    event.preventDefault()
    if (head && status?.defaults && !busy && !pending) {
      submit(modelDraft(head, config, !noHints))
    }
  }

  return (
    <dialog id="model-dialog" ref={dialog} aria-labelledby="model-dialog-title" data-alternate={alternate ? "" : undefined}>
      <form id="config-form" className="stack" onSubmit={handleSubmit}>
        <Layout variant="cfghead">
          <Layout>
            <Heading level={2} id="model-dialog-title">{t("models.configure")}</Heading>
            <Paragraph id="cfg-model" variant="help">{head?.title || "-"}</Paragraph>
          </Layout>
          <Button type="button" variant="ghost" id="model-dialog-close" autoFocus onClick={() => dialog.current.close()}>
            {t("keys.close")}
          </Button>
        </Layout>
        {alternate ? (
          <FieldSet id="runtime-settings" className="cfgfields" disabled={!status?.defaults}>
            <FieldLegend>{t("settings.runtime")}</FieldLegend>
            <FieldGroup className="stack">
              {["whisper", "sherpa", "gigaam_v4"].includes(runtime) && (
                <NumberSetting id="opt-alternate-threads" label={t("settings.threads")} noteId="threads-note"
                  note={t("settings.threadsHint")} min="1" max="16" step="1" inputMode="numeric"
                  placeholder={status?.alternate_threads_default == null ? undefined : String(status.alternate_threads_default)}
                  value={config.alternate_threads ?? ""} onChange={set("alternate_threads")} />
              )}
              {runtime === "whisper" && (
                <NumberSetting id="opt-whisper-beam" label={t("settings.beam")} noteId="beam-note"
                  note={t("settings.beamHint")} min="1" max="10" step="1" inputMode="numeric" required
                  value={config.whisper_beam_size ?? 5} onChange={set("whisper_beam_size")} />
              )}
              {runtime === "parakeet" && head.id !== "nemotron_35_asr" && (
                <NumberSetting id="opt-parakeet-segment" label={t("settings.segment")} noteId="parakeet-segment-note"
                  note={t("settings.segmentHint")} min="5" max="30" step="1" inputMode="numeric" required
                  value={config.parakeet_max_segment ?? 30} onChange={set("parakeet_max_segment")} />
              )}
              {head.id === "nemotron_35_asr" && (
                <OptionSetting id="opt-nemotron-language" label={t("settings.defaultLanguage")} noteId="nemotron-language-note"
                  note={t("settings.languageHint")} items={options(["auto", "ru", "en"], "settings.language.")}
                  value={config.nemotron_language || "auto"} onChange={set("nemotron_language")} />
              )}
              {runtime === "sherpa" && (
                <OptionSetting id="opt-t-one-punctuation" label={t("opt.punctuation")} noteId="t-one-punctuation-note"
                  note={t("settings.toneHint")} items={options(["on", "off"], "mode.")}
                  value={config.punctuation === "off" ? "off" : "on"} onChange={set("punctuation")} />
              )}
            </FieldGroup>
          </FieldSet>
        ) : (
          <FieldSet id="config-editor" className="cfgfields" disabled={!status?.defaults}>
            <FieldSet>
              <FieldLegend>{t("settings.text")}</FieldLegend>
              <FieldGroup className="stack">
                <OptionSetting id="opt-punctuation" label={t("opt.punctuation")} noteId="punctuation-note"
                  note={t("opt.punctuation.note") + " " + t("opt.punctuation." + hintMode)}
                  items={modes} value={config.punctuation || "auto"} onChange={set("punctuation")} />
                <OptionSetting id="opt-itn" label={t("opt.itn")} noteId="itn-note"
                  note={t("opt.itn.note") + " " + t("opt.itn." + hintMode)}
                  items={modes} value={config.itn || "auto"} onChange={set("itn")} />
              </FieldGroup>
            </FieldSet>
            <FieldSet>
              <FieldLegend>{t("settings.audio")}</FieldLegend>
              <FieldGroup className="stack">
                <OptionSetting id="opt-vad" label={t("opt.vad")} noteId="vad-note" note={t("opt.vad.note")}
                  items={[[false, t("vad.off")], [true, t("vad.on")]]} value={String(Boolean(config.vad))}
                  onChange={set("vad", (value) => value === "true")} />
                <OptionSetting id="opt-pool" label={t("opt.pool")} noteId="pool-note" note={t("opt.pool.note")}
                  items={optionsWithCounts("pool.")} value={pool} onChange={changePool} />
                <OptionSetting id="opt-window-concurrency" label={t("opt.window")} noteId="window-note"
                  note={t(pool === 1 ? "opt.window.locked" : "opt.window.note", { pool })}
                  items={optionsWithCounts("window.").map(([value, label]) => [value, label, value > pool])}
                  value={Math.min(pool, Number(config.file_window_concurrency ?? 1))}
                  onChange={set("file_window_concurrency", Number)} disabled={pool === 1} />
              </FieldGroup>
            </FieldSet>
            <FieldSet>
              <FieldLegend>{t("settings.hints")}</FieldLegend>
              <FieldGroup className="stack">
                <OptionSetting id="opt-hotwords-default" label={t("opt.hotwordsDefault")} noteId="dictionary-note" note={t("opt.dictionary.note")}
                  items={[[true, t("dict.on")], [false, t("dict.off")]]} value={String(Boolean(config.hotwords_default))}
                  onChange={set("hotwords_default", (value) => value === "true")} />
                <NumberSetting id="opt-boost" label={t("opt.boost")} noteId="boost-note"
                  note={t(noHints ? "opt.boost.locked" : "opt.boost.note")} value={config.hotwords_boost ?? ""}
                  onChange={set("hotwords_boost")} min="0" max="50" step="any" inputMode="decimal" disabled={noHints} required />
              </FieldGroup>
            </FieldSet>
          </FieldSet>
        )}
        <Layout variant="actions">
          <Button id="btn-deploy" type="submit" disabled={!status?.defaults || !head || busy || pending}>
            {t(head && head.id === status?.engine?.variant ? "head.redeploy" : "head.deploy")}
          </Button>
          <span id="draft-note" className="help">
            {!status?.defaults ? statusError?.message || t("audio.awaitStatus") : hasDraft ? t("settings.draft") : ""}
          </span>
        </Layout>
        <p id="deploy-feedback" role="status">{feedback}</p>
        <progress id="deploy-progress" max="100" value={percent ?? undefined} hidden={percent === null} aria-label={t("head.deploy")} />
      </form>
    </dialog>
  )
}
