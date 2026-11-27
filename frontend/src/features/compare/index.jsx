import { Fragment, useEffect, useRef, useState } from "react";
import { useConsole } from "@/app/use-console";
import { CopyButton } from "@/components/copy-button";
import { Heading, Layout, Paragraph } from "@/components/native/layout";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { cn } from "@/lib/utils";
import { diffTokens } from "./diff.js";
import "./compare.css";

export function Compare({ active }) {
  const { api, status, statusError, heads, catalog, t, page, loadHeads } = useConsole();
  const [selection, setSelection] = useState([]);
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState(null);
  const [error, setError] = useState(null);
  const request = useRef(null);
  const submit = useRef(null);
  const focusAfterPick = useRef(false);
  const keptRunningInSettings = useRef(false);

  const downloaded = heads.filter((head) => head.downloaded);
  const first = downloaded.find((head) => head.id === selection[0]) || downloaded[0];
  const second = downloaded.find((head) => head.id === selection[1] && head !== first) ||
    downloaded.find((head) => head !== first);
  const enabled = status?.compare_enabled === true;
  const changing = ["downloading", "starting"].includes(status?.status);
  const available = enabled && catalog === "ready" && Boolean(second) && !changing;
  const alternate = [first, second].some((head) => head && head.runtime !== "gigastt");
  const engine = status?.engine;
  const stopFirst = Boolean(engine?.running && (status?.compare_single_engine || alternate ||
    (engine.runtime && engine.runtime !== "gigastt")));
  const message = !status ? "audio.awaitStatus" : !enabled ? "compare.disabled" : changing ? "compare.engineChanging"
    : catalog === "loading" ? "compare.catalogLoading" : catalog === "error" ? "compare.catalogError"
      : !second ? "compare.weights" : stopFirst ? "compare.stopFirst" : alternate ? "compare.alternateMethod" : "compare.method";

  useEffect(() => {
    function abort() {
      request.current?.abort();
      request.current = null;
    }
    function leavePage() {
      abort();
      setBusy(false);
    }
    window.addEventListener("pagehide", leavePage);
    return () => {
      window.removeEventListener("pagehide", leavePage);
      abort();
    };
  }, []);

  useEffect(() => {
    if (page === "settings") keptRunningInSettings.current = Boolean(request.current);
    if (!active && page !== "settings" && request.current) {
      request.current.abort();
      request.current = null;
      setBusy(false);
      setOutcome(null);
      setError(null);
    }
  }, [active, page]);

  useEffect(() => {
    if (!enabled && !request.current && !keptRunningInSettings.current) {
      setOutcome(null);
      setError(null);
    }
  }, [enabled]);

  useEffect(() => {
    if (focusAfterPick.current) {
      focusAfterPick.current = false;
      if (active && available && !stopFirst && !busy) submit.current?.focus();
    }
  }, [active, available, busy, file, stopFirst]);

  function choose(index, id) {
    const [a, b] = [first?.id, second?.id];
    setSelection(index === 0 ? [id, id === b ? a : b] : [id === a ? b : a, id]);
    setOutcome(null);
    setError(null);
  }

  function chooseFile(event) {
    const picked = event.target.files[0] || null;
    focusAfterPick.current = Boolean(picked);
    setFile(picked);
    setOutcome(null);
    setError(null);
  }

  async function compare(event) {
    event.preventDefault();
    if (!available || !file || stopFirst || request.current) return;
    const controller = new AbortController();
    request.current = controller;
    const form = new FormData();
    form.append("file", file, file.name);
    form.append("variant_a", first.id);
    form.append("variant_b", second.id);
    setBusy(true);
    setOutcome(null);
    setError(null);
    try {
      const payload = await api("/api/compare", { method: "POST", body: form, signal: controller.signal });
      if (request.current !== controller) return;
      const [a, b] = payload.results;
      const same = a.text === b.text;
      setOutcome({ payload, same, changes: same ? null : diffTokens(a.text, b.text) });
    } catch (error) {
      if (request.current === controller) {
        setError(error);
        void loadHeads();
      }
    } finally {
      if (request.current === controller) {
        request.current = null;
        setBusy(false);
      }
    }
  }

  const stage = outcome ? t(outcome.same ? "compare.same" : outcome.changes ? "compare.diff" : "compare.long") +
    (Number.isFinite(outcome.payload.audio_seconds) ? " · " + t("compare.audio", { value: outcome.payload.audio_seconds.toFixed(2) }) : "")
    : busy ? t("compare.wait") : error?.message || "";
  return (
    <>
      <Layout variant="titleline">
        <p role="status" id="compare-availability">{(!status && statusError?.message) || t(message)}</p>
        <a className="textlink" href="#benchmarks">{t("benchmarks.open")}</a>
      </Layout>
      <a className="textlink" href="#settings" id="compare-settings-link" hidden={!status || enabled}>{t("page.settings")}</a>
      <a className="textlink" href="#status" id="compare-status-link" hidden={!available || !stopFirst}>{t("page.status")}</a>
      <form id="compare-form" hidden={!available} onSubmit={compare}>
        <FieldGroup className="selectrow">
          {[[first, "model-a", "compare.first"], [second, "model-b", "compare.second"]].map(([model, id, label], index) => (
            <Field key={id} data-disabled={busy}>
              <FieldLabel htmlFor={id}>{t(label)}</FieldLabel>
              <NativeSelect id={id} value={model?.id ?? ""} disabled={busy} onChange={(event) => choose(index, event.target.value)} required>
                {downloaded.map((head) => <NativeSelectOption key={head.id} value={head.id}>{head.title}</NativeSelectOption>)}
              </NativeSelect>
            </Field>
          ))}
        </FieldGroup>
        <Layout variant="actions compare-controls">
          <Button ref={submit} type="submit" id="btn-compare" hidden={!file} disabled={!available || busy || !file || stopFirst}>
            {t("compare.run")}
          </Button>
          <label className={cn("filepick", !file && "primary")} id="compare-picker">
            <span id="compare-pick-label">{t(file ? "compare.change" : "btn.file")}</span>
            <Input id="compare-file" type="file" accept="audio/*,.wav,.webm,.opus,.mp3,.ogg,.flac,.m4a" disabled={busy}
              aria-labelledby="compare-pick-label" onChange={chooseFile} required />
          </label>
          <span className="filename" id="compare-name">{file?.name || t("compare.noFile")}</span>
        </Layout>
      </form>
      <a className="textlink" href="#models" id="compare-models" hidden={!["compare.catalogError", "compare.weights"].includes(message)}>{t("page.models")}</a>
      <p role="status" id="compare-stage">{stage}</p>
      <Layout id="compare-results" variant="panelgrid">
        {outcome?.payload.results.map((result, index) => (
          <ComparisonResult key={result.variant} result={result} change={outcome.changes?.[index]} index={index}
            title={heads.find((head) => head.id === result.variant)?.title || result.variant} t={t} active={active} />
        ))}
      </Layout>
      <Paragraph id="compare-time-note" variant="help" hidden={!outcome}>{t("compare.timing")}</Paragraph>
    </>
  );
}

function ComparisonResult({ result, change, index, title, t, active }) {
  const target = `comparison-${index}`;
  return (
    <Card className="panel stack">
      <CardHeader>
        <CardDescription>{t(index ? "compare.second" : "compare.first")}</CardDescription>
        <CardTitle><Heading level={2}>{title}</Heading></CardTitle>
      </CardHeader>
      <CardContent className="compare-result-content">
        <code>{result.variant}</code>
        <Paragraph variant="sample" id={target}>
          {change?.length ? change.map(({ text, changed }, ordinal) =>
            changed ? <mark key={ordinal}>{text}</mark> : <Fragment key={ordinal}>{text}</Fragment>
          ) : result.text || t("test.empty")}
        </Paragraph>
        <Paragraph variant="help">{t("compare.elapsed", { value: result.elapsed.toFixed(2) })}</Paragraph>
      </CardContent>
      <CardFooter>
        <CopyButton t={t} target={target} className="copy" value={result.text} active={active} />
      </CardFooter>
    </Card>
  );
}
