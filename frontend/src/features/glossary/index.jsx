import { useEffect, useLayoutEffect, useRef, useState } from "react"

import { useConsole } from "@/app/use-console"
import { Heading, Layout, Paragraph } from "@/components/native/layout"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"

import { glossaryCoverage } from "./coverage"
import { entryText, fold, groupIssues, mergePhrases } from "./phrases"
import { useGlossary } from "./use-glossary"

export function Glossary({ active }) {
  const { api, heads, status, mode, jsonLimit, t, lang, refreshStatus } = useConsole()
  const store = useGlossary(api, active, status?.engine?.variant || status?.defaults?.variant,
    status?.status, status?.glossary_count)
  const [input, setInput] = useState("")
  const [hint, setHint] = useState(null)
  const [busy, setBusy] = useState(false)
  const [flash, setFlash] = useState(null)
  const saving = useRef(false)
  const inputRef = useRef(null)
  const listRef = useRef(null)
  const nextFocus = useRef(null)
  const text = entryText(store.entries)
  const dirty = text !== store.applied
  const groups = groupIssues(store.issues)
  const known = new Set(store.entries.map(({ phrase }) => fold(phrase)))
  const missing = (store.payload?.env_missing || []).filter((phrase) => !known.has(fold(phrase)))
  const activeModel = heads.find(({ id }) => id === store.payload?.variant)
  const coverage = glossaryCoverage(store.payload, store.entries, dirty, activeModel?.title, t)
  const disabled = !store.payload || busy

  useEffect(() => {
    if (!flash) return
    listRef.current?.children[flash.index]?.scrollIntoView({ block: "nearest", behavior: "instant" })
    const timer = setTimeout(() => setFlash(null), 900)
    return () => clearTimeout(timer)
  }, [flash])

  useLayoutEffect(() => {
    if (nextFocus.current === null) return
    const after = listRef.current?.children[Math.min(nextFocus.current, store.entries.length - 1)]
    const control = after?.querySelector("button") || inputRef.current
    control?.focus()
    nextFocus.current = null
  }, [store.entries])

  function checkedBody(value) {
    const body = JSON.stringify({ text: value })
    if (mode === "owner" && Number.isFinite(jsonLimit) && new TextEncoder().encode(body).byteLength > jsonLimit) {
      setHint({ key: "glossary.jsonLimit", params: { limit: jsonLimit } })
      return null
    }
    return body
  }

  function addPhrases(value) {
    const { entries, added, duplicate } = mergePhrases(store.entries, value)
    if (added) {
      store.setEntries(entries)
      setHint({ key: "glossary.added" })
    } else if (duplicate !== null) {
      setHint({ key: "glossary.duplicate" })
      setFlash({ index: duplicate })
    }
  }

  function commitInput() {
    if (!input.trim() || disabled) return
    addPhrases(input)
    setInput("")
  }

  function removePhrase(index, moveFocus = true) {
    if (moveFocus) nextFocus.current = index
    store.setEntries(store.entries.filter((_, entry) => entry !== index))
    setHint({ key: "glossary.removed" })
  }

  function handleKeys(event) {
    // Safari может отправить Enter сразу после завершения IME.
    if (event.nativeEvent.isComposing || (event.key === "Enter" && event.keyCode === 229)) return
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault()
      commitInput()
    } else if (event.key === "Backspace" && !input && store.entries.length) {
      removePhrase(store.entries.length - 1, false)
    }
  }

  function handlePaste(event) {
    const value = event.clipboardData?.getData("text")
    if (value && /[\n,]/.test(value)) {
      event.preventDefault()
      addPhrases(value)
      setInput("")
    }
  }

  async function importFile(event) {
    const picker = event.currentTarget
    const file = picker.files[0]
    picker.value = ""
    if (!file || disabled) return
    setBusy(true)
    try {
      const { entries, added, skipped } = mergePhrases(store.entries, await file.text())
      if (checkedBody(entryText(entries)) === null) return
      store.setEntries(entries)
      setHint({ key: added ? "glossary.imported" : "glossary.importedNothing", params: { added, skipped } })
    } catch (error) {
      setHint({ error })
    } finally {
      setBusy(false)
    }
  }

  function exportFile() {
    if (!store.entries.length) {
      setHint({ key: "glossary.empty" })
      return
    }
    const url = URL.createObjectURL(new Blob([text + "\n"], { type: "text/plain;charset=utf-8" }))
    const link = document.createElement("a")
    link.href = url
    link.download = t("glossary.exportName")
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    setHint({ key: "glossary.saved" })
  }

  async function apply() {
    if (disabled || !dirty || saving.current) return
    const body = checkedBody(text)
    if (body === null) return
    saving.current = true
    setBusy(true)
    store.pauseRead()
    setHint({ key: "glossary.applying" })
    try {
      const payload = await api("/api/glossary", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      })
      const engine = status?.engine
      const usesGlossary = engine?.running && (!engine.runtime || engine.runtime === "gigastt")
      const key = !payload.applied ? "glossary.applyFailed"
        : payload.mode === "prompt" ? "glossary.storedPrompt"
        : payload.mode === "unsupported" ? "glossary.storedForSupported"
        : usesGlossary ? "glossary.applied" : "glossary.stored"
      setHint({ key })
      await store.load({ keepDraft: false, issues: payload.issues })
      if (payload.issues) store.setIssues(payload.issues)
      await refreshStatus()
    } catch (error) {
      setHint({ error })
    } finally {
      store.resumeRead()
      saving.current = false
      setBusy(false)
    }
  }

  async function retry() {
    if (await store.load()) setHint(null)
  }

  const hintText = store.error?.message || hint?.error?.message || (hint?.key ? t(hint.key, {
    ...hint.params,
    ...(hint.key === "glossary.jsonLimit" && { limit: hint.params.limit.toLocaleString(lang) }),
    ...(hint.key === "glossary.imported" && {
      skipped: hint.params.skipped ? t("glossary.importedSkipped", { count: hint.params.skipped }) : "",
    }),
  }) : "")

  return (
    <Layout variant="panel stack">
      <Layout variant="titleline">
        <Heading level={2} id="phrases-title">{t("glossary.phrases")}</Heading>
        <Badge id="glossary-count" variant="secondary">
          {store.entries.length ? t("glossary.count", { count: store.entries.length }) : t("glossary.none")}
        </Badge>
      </Layout>
      <Paragraph variant="help" id="glossary-intro">{t("glossary.intro")}</Paragraph>
      <div id="glossary-editor" aria-disabled={disabled || undefined}>
        <FieldGroup className="block [container-type:normal]">
          <Field id="tags" data-disabled={disabled || undefined}>
            <FieldLabel htmlFor="add-phrase">{t("glossary.addAria")}</FieldLabel>
            <span className="tag-entry">
              <Input ref={inputRef} id="add-phrase" type="text" spellCheck={false} autoComplete="off" disabled={disabled}
                value={input} onChange={(event) => setInput(event.currentTarget.value)} onKeyDown={handleKeys} onPaste={handlePaste} />
              <Button type="button" variant="outline" id="btn-add" disabled={disabled} onClick={commitInput}>{t("glossary.add")}</Button>
            </span>
          </Field>
        </FieldGroup>
        <Layout variant="actions">
          <Button type="button" id="btn-glossary" onClick={apply} disabled={disabled || !dirty}>{t("btn.apply")}</Button>
          <label className="filepick"><span>{t("btn.import")}</span>
            <input type="file" id="glossary-file" accept=".txt,.csv,text/plain,text/csv" aria-label={t("btn.import")}
              disabled={disabled} onChange={importFile} />
          </label>
          <Button type="button" variant="outline" id="btn-export" disabled={disabled} onClick={exportFile}>{t("btn.export")}</Button>
        </Layout>
        <ul id="tag-list" ref={listRef} aria-labelledby="phrases-title">
          {store.entries.map((entry, index) => {
            const dropped = coverage.dropped.has(fold(entry.phrase))
            return (
              <li key={entry.phrase + index} className="tag" data-index={index} data-dropped={dropped || undefined}
                data-flash={flash?.index === index || undefined} title={dropped ? t("glossary.dropTitle") : undefined}>
                <span className="tag-text">{entry.phrase}</span>
                {entry.weight && <span className="tag-weight" title={t("glossary.weight")}>·{entry.weight}</span>}
                <Button type="button" variant="ghost" size="icon" className="tag-remove" disabled={disabled}
                  aria-label={t("glossary.remove", { phrase: entry.phrase })} onClick={() => removePhrase(index)}>×</Button>
              </li>
            )
          })}
        </ul>
        <p id="glossary-reach" data-loss={Boolean(coverage.loss)} role="status">{coverage.text}</p>
        <Paragraph id="dropped-hint" variant="help">{coverage.help}</Paragraph>
        <div id="glossary-issues" hidden={!groups.size}>
          {[...groups].map(([code, phrases]) => <Paragraph key={code}>{t("issue." + code, { list: phrases.join(", ") })}</Paragraph>)}
        </div>
        <p id="glossary-env" hidden={!missing.length}>
          <span id="glossary-env-text">{t("glossary.envMissing", { count: missing.length, list: missing.join(", ") })}</span>{" "}
          <Button type="button" variant="outline" id="btn-glossary-env" disabled={disabled} onClick={() => addPhrases(missing.join("\n"))}>
            {t("glossary.envAdd")}
          </Button>
        </p>
      </div>
      <p role="status" id="glossary-hint">{hintText}</p>
      <Button type="button" variant="outline" id="glossary-retry" hidden={!store.error} onClick={retry}>{t("head.retry")}</Button>
    </Layout>
  )
}
